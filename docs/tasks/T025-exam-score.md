# T025 — Exam rubric scoring (estimate) + calibration

**Branch:** `task/T025-exam-score` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
After an exam, Sameer gets a short, honest estimate next to the feedback. It has four criteria, each with a band, a one-sentence reason and a quote from what he said, clearly labelled as an estimate. A calibration eval shows the estimate ranks B1 < B2 < C1 transcripts correctly and doesn't jump around.

## Context
- D021 (exam presets, no official material) and the proposed D022 (see below).
- The exam history is complete in `Session.history`. Trimming only affects the chat context. `format_feedback_transcript()` renders `[Moderation]` markers as `--- … ---` headings.
- Feedback runs in `Session.feedback()` (thermal check → LLM → `feedback` message).
- **Calibration set (written by the lead; do not edit):** `scripts/score_cases.json`.
  - 3 topics × B1/B2/C1, plus `wohnen_B2_offtask` (B2 language, a talk that ignores its card).
  - Within a topic, Kerstin's lines are identical, so only the learner's level varies.
  - It is a **hold-out** set: nothing from it may appear in the prompt.
- Text only: the STT transcript can't show pronunciation or fluency, and STT may smooth over or add errors. The UI says so.

## Proposed decision D022 (lead records it in DECISIONS.md on acceptance)
- **Own scale:** an estimate on our own 4-band scale per criterion:
  - 1 „unter B2“
  - 2 „B2 knapp“
  - 3 „B2 sicher“
  - 4 „über B2“
- **Criteria:** Aufgabenerfüllung, Kohärenz, Wortschatz, Grammatik.
- **Not official:** no official point tables, no pass/fail, no "telc/Goethe score".
- **Overall:** the overall band is the **median of the four bands**, rounded down. It is computed in code, not by the LLM.
- **Evidence:** every reason must quote the learner verbatim; a quote that isn't in the learner's text is dropped.
- **Privacy:** nothing is stored. The score lives in memory and goes to the client only.

## Spec
1. **LLM** (`llm.py`): `chat(..., fmt: str | None = None, seed: int | None = None)`.
   - `fmt` → payload `"format"` (Ollama JSON mode);
   - `seed` overrides the random/`llm_seed` seed;
   - existing callers are unchanged.
2. **Prompt** `backend/prompts/score.md` (German; written by you, reviewed by the lead).
   - Placeholders: `{explanation_language}` (same labels as feedback), `{cards}` (the learner's cards for this exam, as text), `{talk_words}` (word count of the learner's talk part, computed in code), `{transcript}`.
   - Content:
     - define the 4 criteria and 4 bands in plain words;
     - score **only the lines of „Lernende Person“**; Kerstin's lines are context;
     - judge Aufgabenerfüllung against the card points and the part tasks;
     - quote evidence verbatim, max. 12 words;
     - for Grammatik with band ≤ 3, the evidence should be a line that contains an error;
     - write reasons in `{explanation_language}`, 1 sentence each.
   - Output JSON only:
     ```json
     {"aufgabe":{"band":1,"reason":"…","evidence":"…"},
      "kohaerenz":{…},"wortschatz":{…},"grammatik":{…}}
     ```
   - **No sentence from `scripts/score_cases.json` in the prompt, and no invented example transcripts either** (describe the bands abstractly).
3. **Module** `backend/kerstin/score.py` (pure, no I/O):
   - `CRITERIA` (key → German label) and `BANDS` (1–4 → label).
   - `learner_text(history) -> str` (non-moderation user messages) and `talk_word_count(history, plan) -> int`.
   - `score_prompt(store, history, plan, lang) -> str`, via a new `PromptStore.score_prompt(...)` in `prompts.py`.
   - `parse_score(raw: str, learner: str) -> ExamScore | None`:
     - strict: all 4 keys, `band` an int 1–4 (an int-valued string such as `"3"` is accepted), `reason` a non-empty str;
     - `evidence` is kept only if its normalised form (lowercase, collapsed whitespace, punctuation stripped) is a substring of the normalised learner text; otherwise it becomes `None` and `dropped_evidence += 1`;
     - anything else returns `None`.
   - `overall_band(bands) -> int` (median, rounded down).
4. **Session** (`session.py`), after the `feedback` message is sent, if `self.exam is not None`:
   - if `learner_text` has fewer than 60 words: send `{"type":"exam_score","error":"zu wenig Material für eine Einschätzung"}`;
   - otherwise:
     - run the thermal check (hot → `exam_score` with `error`, no LLM call);
     - send `status` `score_running`;
     - call `llm.chat(..., fmt="json", temperature=0.0, seed=deps.score_seed, max_tokens=500)` with the same model choice as feedback;
     - on a parse failure, retry once; if it still fails → `exam_score` with `error`;
     - on success, send:
       ```json
       {"type":"exam_score",
        "criteria":[{"key","label","band","band_label","reason","evidence"}],
        "overall_band","overall_label",
        "note":"Einschätzung aus dem Transkript – keine offizielle Bewertung. Aussprache und Flüssigkeit werden nicht bewertet; die Spracherkennung kann Fehler glätten oder hinzufügen."}
       ```
   - log the duration and `dropped_evidence`, never the text.
   - `Deps.score_seed: int = 7`; config `KERSTIN_SCORE_SEED`.
   - Free-conversation feedback is unchanged.
5. **UI** (`app.js`, `style.css`, `index.html` if needed):
   - an „Einschätzung“ box below the feedback, built with `createElement`/`textContent` only;
   - it shows the note (always visible), the overall band, and a 4-row table: criterion · band label · reason · „…“-quoted evidence (omitted if `null`);
   - `error` → a one-line message;
   - `status: score_running` → „Einschätzung wird erstellt …“;
   - a new `session` clears the box.
6. **Eval** `scripts/score_eval.py` + `make score-eval`:
   - Build an exam history for each case: a `Vortrag und Diskussion`-shaped sequence using the real `format_feedback_transcript` input shape (marker for the talk part, the case's talk lines as user messages, a discussion marker, Kerstin line / learner line pairs) and the case's card.
   - Run 3 variants per case: `orig`, `drop` (the last discussion line removed), `noisy` (STT-like: punctuation removed, all lowercase except the first word of each line).
   - `cool_down()` before every call; `--model` (default `gemma4:26b`).
   - Print per case and variant: the 4 bands, the overall band, ms, `dropped_evidence`; then every reason + evidence for the `orig` variant.
   - **Checks** (print each with PASS/FAIL; exit 1 on any FAIL):
     - `parse`: 30/30 parsed (after at most 1 retry each);
     - `order`: for each topic, mean band (4 criteria, `orig`) B1 < B2 < C1 strictly, in 3/3 topics;
     - `levels` (means over the `orig` variant): B1 cases ≤ 1.75; B2 cases (the 3 on-task ones) in [2.0, 3.25]; C1 cases ≥ 3.25;
     - `offtask`: `wohnen_B2_offtask` Aufgabenerfüllung ≤ 2 and ≤ `wohnen_B2` Aufgabenerfüllung − 1; its Wortschatz and Grammatik each within ±1 of `wohnen_B2`;
     - `stability`: for every case and criterion, max − min over the 3 variants ≤ 1; overall band identical in ≥ 2 of 3 variants for ≥ 9/10 cases;
     - `evidence`: dropped evidence ≤ 10 % of all evidence fields;
     - `latency`: report p50/max ms (no threshold; report it).
   - Don't tune thresholds or cases to pass. If a check fails, report it; the lead decides.
7. **Tests:**
   - `parse_score`: valid JSON, a missing key, band 0/5, string band, a fabricated evidence quote → dropped, punctuation/case-insensitive evidence match;
   - `overall_band`;
   - `learner_text` excludes Kerstin and markers;
   - session: exam end → `feedback` then `exam_score` (fake LLM returning fixed JSON); a too-short exam → `exam_score.error` without an LLM call; free conversation → no `exam_score`;
   - **hold-out test:** no 6-word sequence from `scripts/score_cases.json` (normalised) appears in `backend/prompts/score.md`.
8. **Report:** paste the full eval output. Include a before/after sample for the new prompt: one real `orig` output for `umwelt_B2`, with reasons. Report the added time at the end of an exam (p50 ms), measured with `gemma4:26b`.

## Files allowed to change
- `backend/kerstin/llm.py` (the `fmt`/`seed` params only), `backend/kerstin/score.py` (new), `backend/kerstin/prompts.py` (`score_prompt` only), `backend/kerstin/session.py`, `backend/kerstin/config.py` (`KERSTIN_SCORE_SEED`), `backend/kerstin/main.py` (only to pass the setting into `Deps`)
- `backend/prompts/score.md` (new)
- `frontend/app.js`, `frontend/style.css`, `frontend/index.html`
- `scripts/score_eval.py` (new), `Makefile` (`score-eval` target)
- `backend/tests/test_score.py` (new), `backend/tests/test_exam.py`
- `docs/PROTOCOL.md` (`exam_score`, `score_running`), `.env.example` (`KERSTIN_SCORE_SEED`), this task file

## Out of scope
- `scripts/score_cases.json` (lead-owned, read-only), `persona.md`, `feedback.md`, `exam.md`, `exam.json`.
- Storing scores, score history or trends (a later opt-in task, if any).
- Pronunciation/fluency from audio.
- A separate scoring model. Use the feedback model choice, including its eviction guard.

## Acceptance criteria
- [ ] `make test` and `make lint` pass, including the hold-out test.
- [ ] `make score-eval` output pasted in full. Each check is PASS, or FAIL reported honestly with no tuning.
- [ ] Free-conversation `end` sends exactly what it sent before (no `exam_score`); test proves it.
- [ ] Exam `end` sends `feedback` first, then `exam_score`. The score box always shows the "not official / no pronunciation" note.
- [ ] No score or transcript is written to disk or logs (grep the diff for `open(`, `write`, and `log.*text`).
- [ ] No new dependencies.

## Worker report (Kilo Code fills this in)
- **Changed files:**
- **How tested:**
- **Measurements (if any):**
- **Deviations from spec / extra files touched:**
- **New dependencies (+license):**
- **Open questions:**

## Review (Claude Code fills this in)
- **Verdict:**
- **Notes:**
