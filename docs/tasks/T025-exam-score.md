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
- **Changed files:** `backend/kerstin/llm.py` (`fmt`/`seed`), `backend/kerstin/score.py` (new), `backend/kerstin/prompts.py` (`score_prompt`), `backend/kerstin/session.py`, `backend/kerstin/config.py` (`score_seed`), `backend/kerstin/main.py` (Deps wiring), `backend/prompts/score.md` (new), `frontend/app.js`, `frontend/index.html`, `frontend/style.css`, `scripts/score_eval.py` (new), `Makefile` (`score-eval`), `backend/tests/test_score.py` (new), `backend/tests/test_exam.py`, `docs/PROTOCOL.md`, `.env.example`.
- **How tested:** `make test` → 246 Python tests + 33 Node tests passed. `make lint` → ruff passed. The hold-out check in `test_score.py` finds 0 six-word sequences from `scripts/score_cases.json` in `score.md`. A headless Chromium load on port 8771 confirmed the `Einschätzung` box, its always-visible note, and hidden table render without console errors. `make score-eval` was run with `gemma4:26b`; full output is below. It passes `parse` (30/30), `order`, `offtask`, `stability`, and `evidence`; `levels` FAILS because the B1 `medien` and `umwelt` means are 2.0 (threshold ≤ 1.75). No thresholds or eval checks were changed.
- **Measurements (if any):** Scoring call latency from the final eval: **p50 4623 ms, max 5457 ms** with `gemma4:26b` (excludes the preceding feedback call). The eval had 0 retries. `umwelt_B2` before/after:
  - Before (initial prompt): bands `[4, 4, 3, 3]`, overall 3; Aufgabe 4 (all points comprehensively), Kohärenz 4 (smooth transitions), Wortschatz 3 (appropriate but standard), Grammatik 3 (complex structures, minor preposition error).
  - After (final prompt): bands `[3, 3, 3, 3]`, overall 3; Aufgabe 3 (all points with examples/position), Kohärenz 3 (well-structured, appropriate connectors), Wortschatz 3 (varied, topic-specific), Grammatik 3 (mostly correct, minor preposition/case errors).
- **Deviations from spec / extra files touched:** `levels` remains failing; the B1 calibration cases are still rated too high (`wohnen_B1` 1.75, `medien_B1` 2.0, `umwelt_B1` 2.0). I did not change the thresholds or cases. One existing `test_session.py` contract requires a zero-learner-line exam feedback to contain only the empty feedback message, so that zero-line path does not send `exam_score`; non-empty short exams do send the error. No files outside the allowed list were touched; the pre-existing `.gitignore` change is untouched.
- **New dependencies (+license):** None. `scripts/score_eval.py` uses the existing `websockets`/`httpx` environment and is not imported by the app.
- **Open questions:** The lead decides whether the B1 overestimation needs rubric work or whether the eval threshold should remain as a reported failure. The zero-learner-line behavior above is a compatibility choice; confirm it matches the desired exam UX.

### Full `make score-eval` output
```text
.venv/bin/python scripts/score_eval.py
Model: gemma4:26b | seed: 7 | variants: orig, drop, noisy
Cases: 10 | cool_down: 76→70 °C
GPU wohnen_B1 orig attempt 1: 62 °C
wohnen_B1            orig  bands=[2, 2, 2, 1] overall=2 ms=4547 dropped=0 attempt=1
GPU wohnen_B1 drop attempt 1: 68 °C
wohnen_B1            drop  bands=[2, 2, 2, 1] overall=2 ms=4260 dropped=0 attempt=1
GPU wohnen_B1 noisy attempt 1: 70 °C
wohnen_B1            noisy bands=[2, 2, 2, 1] overall=2 ms=4471 dropped=0 attempt=1
GPU wohnen_B2 orig attempt 1: 70 °C
wohnen_B2            orig  bands=[3, 3, 3, 3] overall=3 ms=4201 dropped=0 attempt=1
GPU wohnen_B2 drop attempt 1: 71 °C
wohnen_B2            drop  bands=[3, 3, 3, 3] overall=3 ms=4120 dropped=0 attempt=1
GPU wohnen_B2 noisy attempt 1: 71 °C
wohnen_B2            noisy bands=[3, 3, 3, 2] overall=3 ms=4411 dropped=0 attempt=1
GPU wohnen_C1 orig attempt 1: 72 °C
wohnen_C1            orig  bands=[4, 4, 4, 4] overall=4 ms=4373 dropped=0 attempt=1
GPU wohnen_C1 drop attempt 1: 73 °C
wohnen_C1            drop  bands=[4, 4, 4, 4] overall=4 ms=3860 dropped=0 attempt=1
GPU wohnen_C1 noisy attempt 1: 73 °C
wohnen_C1            noisy bands=[3, 3, 3, 3] overall=3 ms=4748 dropped=1 attempt=1
GPU wohnen_B2_offtask orig attempt 1: 73 °C
wohnen_B2_offtask    orig  bands=[1, 2, 2, 3] overall=2 ms=5029 dropped=0 attempt=1
GPU wohnen_B2_offtask drop attempt 1: 73 °C
wohnen_B2_offtask    drop  bands=[1, 1, 1, 2] overall=1 ms=4588 dropped=0 attempt=1
GPU wohnen_B2_offtask noisy attempt 1: 74 °C
wohnen_B2_offtask    noisy bands=[1, 2, 1, 2] overall=1 ms=5195 dropped=0 attempt=1
GPU medien_B1 orig attempt 1: 74 °C
medien_B1            orig  bands=[2, 2, 2, 2] overall=2 ms=4926 dropped=0 attempt=1
GPU medien_B1 drop attempt 1: 74 °C
medien_B1            drop  bands=[2, 2, 2, 2] overall=2 ms=4407 dropped=0 attempt=1
GPU medien_B1 noisy attempt 1: 75 °C
medien_B1            noisy bands=[2, 2, 2, 1] overall=2 ms=4519 dropped=0 attempt=1
GPU medien_B2 orig attempt 1: 74 °C
medien_B2            orig  bands=[3, 3, 3, 3] overall=3 ms=5086 dropped=0 attempt=1
GPU medien_B2 drop attempt 1: 75 °C
medien_B2            drop  bands=[3, 3, 3, 3] overall=3 ms=4350 dropped=0 attempt=1
GPU medien_B2 noisy attempt 1: 75 °C
medien_B2            noisy bands=[3, 3, 3, 2] overall=3 ms=5398 dropped=0 attempt=1
GPU medien_C1 orig attempt 1: 75 °C
medien_C1            orig  bands=[4, 4, 4, 4] overall=4 ms=5277 dropped=2 attempt=1
GPU medien_C1 drop attempt 1: 75 °C
medien_C1            drop  bands=[4, 4, 4, 4] overall=4 ms=5457 dropped=2 attempt=1
GPU medien_C1 noisy attempt 1: 75 °C
medien_C1            noisy bands=[4, 4, 4, 3] overall=4 ms=5106 dropped=1 attempt=1
GPU umwelt_B1 orig attempt 1: 76 °C
GPU umwelt_B1 orig attempt 1: 76 °C >= 76 °C, cooling to 70 °C ...
GPU umwelt_B1 orig attempt 1: 68 °C
GPU umwelt_B1 orig attempt 1: cooled to 68 °C, continuing
umwelt_B1            orig  bands=[2, 2, 2, 2] overall=2 ms=5045 dropped=0 attempt=1
GPU umwelt_B1 drop attempt 1: 73 °C
umwelt_B1            drop  bands=[2, 2, 2, 2] overall=2 ms=4612 dropped=0 attempt=1
GPU umwelt_B1 noisy attempt 1: 74 °C
umwelt_B1            noisy bands=[2, 2, 2, 1] overall=2 ms=4634 dropped=0 attempt=1
GPU umwelt_B2 orig attempt 1: 75 °C
umwelt_B2            orig  bands=[3, 3, 3, 3] overall=3 ms=4729 dropped=0 attempt=1
GPU umwelt_B2 drop attempt 1: 75 °C
umwelt_B2            drop  bands=[3, 3, 3, 3] overall=3 ms=4269 dropped=0 attempt=1
GPU umwelt_B2 noisy attempt 1: 75 °C
umwelt_B2            noisy bands=[3, 3, 3, 2] overall=3 ms=4950 dropped=0 attempt=1
GPU umwelt_C1 orig attempt 1: 75 °C
umwelt_C1            orig  bands=[4, 4, 4, 4] overall=4 ms=5061 dropped=0 attempt=1
GPU umwelt_C1 drop attempt 1: 75 °C
umwelt_C1            drop  bands=[4, 4, 4, 4] overall=4 ms=4541 dropped=0 attempt=1
GPU umwelt_C1 noisy attempt 1: 75 °C
umwelt_C1            noisy bands=[3, 3, 3, 3] overall=3 ms=4720 dropped=0 attempt=1
parse: PASS — 30/30 parsed
order: PASS — wohnen B1=1.75 B2=3.0 C1=4.0; medien B1=2.0 B2=3.0 C1=4.0; umwelt B1=2.0 B2=3.0 C1=4.0
levels: FAIL — B1=wohnen_B1:1.75, medien_B1:2.0, umwelt_B1:2.0; B2=wohnen_B2:3.0, medien_B2:3.0, umwelt_B2:3.0; C1=wohnen_C1:4.0, medien_C1:4.0, umwelt_C1:4.0
offtask: PASS — aufgabe=1/3 wortschatz=2/3 grammatik=3/3
stability: PASS — max criterion spread=1; overall stable in 10/10 cases
evidence: PASS — 6/120 dropped (5.0%)
latency: p50=4623 ms max=5457 ms
retries: 0 calls needed a retry

Orig reasons and evidence

wohnen_B1 (B1):
  overall: 2 (B2 knapp)
  Aufgabenerfüllung: 2 (B2 knapp) — The learner addresses all points from the card, but the development of arguments and examples is very minimal. ['Die Stadt hat viele Vorteile, zum Beispiel man hat Bus und Bahn']
  Kohärenz: 2 (B2 knapp) — The presentation follows a logical structure using simple connectors like 'aber' and 'weil'. ['Die Stadt hat viele Vorteile, zum Beispiel man hat Bus und Bahn']
  Wortschatz: 2 (B2 knapp) — The vocabulary is functional and includes some topic-related words, but relies heavily on basic everyday terms. ['In meinem Heimatland viele Leute wohnen in große Städte']
  Grammatik: 1 (unter B2) — There are frequent and clear errors in basic structures, particularly regarding word order and case. ['In meinem Heimatland viele Leute wohnen in große Städte']

wohnen_B2 (B2):
  overall: 3 (B2 sicher)
  Aufgabenerfüllung: 3 (B2 sicher) — The learner addresses all points of the task with clear examples and a personal opinion. ['Man ist mit öffentlichen Verkehrsmitteln schnell überall']
  Kohärenz: 3 (B2 sicher) — The presentation is well-structured and uses appropriate connectors to link ideas. ['deshalb habe ich zuerst in einer WG gewohnt']
  Wortschatz: 3 (B2 sicher) — The vocabulary is varied and includes topic-specific terms like 'Kulturangebot' or 'Busverbindungen'. ['Ein großer Nachteil sind allerdings die hohe Mieten']
  Grammatik: 3 (B2 sicher) — The sentence structures are mostly correct and include complex subordinate clauses. ['Wenn man aber Kinder hat, würde ich eher...']

wohnen_C1 (C1):
  overall: 4 (über B2)
  Aufgabenerfüllung: 4 (über B2) — The learner addresses all points of the task comprehensively and provides a nuanced personal opinion. ['Die Vorteile liegen auf der Hand – kurze Wege, ein dichtes Nahverkehrsnetz']
  Kohärenz: 4 (über B2) — The contribution is logically structured with sophisticated transitions and a clear argumentative thread. ['Dem stehen jedoch erhebliche Nachteile gegenüber']
  Wortschatz: 4 (über B2) — The vocabulary is precise, varied, and includes sophisticated idiomatic expressions like 'der springende Punkt'. ['Genau das ist für mich der springende Punkt.']
  Grammatik: 4 (über B2) — The learner uses complex sentence structures and advanced grammatical constructions almost without errors. ['Sobald Faktoren wie Familie oder Ruhe an Bedeutung gewinnen']

wohnen_B2_offtask (B2):
  overall: 2 (B2 knapp)
  Aufgabenerfüllung: 1 (unter B2) — The learner fails to address the required points regarding the situation in their home country or advantages/disadvantages of city living, instead talking about a vacation in Portugal. ['Letztes Jahr war ich im Urlaub in Portugal']
  Kohärenz: 2 (B2 knapp) — The speaker uses simple connectors like 'und' and 'aber' to link ideas, but the content lacks a logical connection to the assigned topic. ['Das Essen war sehr lecker, besonders der Fisch']
  Wortschatz: 2 (B2 knapp) — The vocabulary is limited to everyday words and does not include topic-specific terms for urban living or housing. ['Ich kann Portugal wirklich jedem empfehlen']
  Grammatik: 3 (B2 sicher) — The grammatical structures used are mostly correct, including subordinate clauses with 'obwohl' and 'weil'. ['obwohl wir kaum Portugiesisch sprechen konnten']

medien_B1 (B1):
  overall: 2 (B2 knapp)
  Aufgabenerfüllung: 2 (B2 knapp) — The learner addresses all points from the card, but the development of the points is quite brief and lacks depth. ['Es gibt Chancen, zum Beispiel man kann mit Familie in mein Land sprechen.']
  Kohärenz: 2 (B2 knapp) — The contribution is logically structured with simple connectors like 'aber' and 'zum Beispiel' to link ideas. ['Aber es gibt auch Risiken, viele Leute schreiben böse Kommentare.']
  Wortschatz: 2 (B2 knapp) — The vocabulary is functional and includes some topic-related words, but remains mostly at a basic level. ['viele Leute schreiben böse Kommentare und man verliert viel Zeit.']
  Grammatik: 2 (B2 knapp) — The basic sentence structures are mostly correct, though there are noticeable errors in word order and case. ['Oder die Firma muss kontrollieren den Ausweis.']

medien_B2 (B2):
  overall: 3 (B2 sicher)
  Aufgabenerfüllung: 3 (B2 sicher) — The learner addresses all points of the prompt with relevant examples and a clear personal opinion. ['Soziale Medien bieten viele Chancen, zum Beispiel kann man sich schnell informieren']
  Kohärenz: 3 (B2 sicher) — The presentation is well-structured and uses appropriate connectors to link ideas logically. ['Deshalb habe ich letztes Jahr für einen Monat alle Apps gelöscht']
  Wortschatz: 3 (B2 sicher) — The vocabulary is varied and includes topic-specific terms like 'Falschinformationen' or 'Datenschutz'. ['Risiken wie Falschinformationen oder Mobbing, besonders für Jugendliche']
  Grammatik: 3 (B2 sicher) — The sentence structures are mostly correct, though a minor error in a relative clause is present. ['feste Zeiten setzen, in den man offline ist']

medien_C1 (C1):
  overall: 4 (über B2)
  Aufgabenerfüllung: 4 (über B2) — The learner addresses all points of the presentation and the discussion question with high depth and nuance. ['Ich plädiere daher nicht für Verzicht, sondern für Medienkompetenz']
  Kohärenz: 4 (über B2) — The contribution is perfectly structured with sophisticated transitions and a logical flow of arguments. [None]
  Wortschatz: 4 (über B2) — The vocabulary is highly precise, academic, and uses sophisticated terms like 'ambivalente Rolle' or 'vermehrt'. [None]
  Grammatik: 4 (über B2) — The learner uses complex sentence structures and advanced grammatical constructions almost without errors. ['...ohne sich von ihnen vereinnahmen zu lassen.']

umwelt_B1 (B1):
  overall: 2 (B2 knapp)
  Aufgabenerfüllung: 2 (B2 knapp) — The learner addresses all points from the card, but the development of advantages and disadvantages is very brief. ['Das ist gut für die Umwelt und auch für die Gesundheit.']
  Kohärenz: 2 (B2 knapp) — The contribution is structured with simple connectors like 'und' and 'aber', creating a basic logical flow. ['Ich fahre mit Fahrrad zur Arbeit und ich kaufe keine Plastiktüte.']
  Wortschatz: 2 (B2 knapp) — The vocabulary is functional and includes some topic-related words like 'Müll trennen' or 'Regierung', but remains mostly at an everyday level. ['In meinem Land die Leute trennen nicht den Müll']
  Grammatik: 2 (B2 knapp) — The basic sentence structures are mostly correct, though there are noticeable errors in word order and preposition usage. ['Aber ich möchte reisen nach Spanien, weil da ist warm.']

umwelt_B2 (B2):
  overall: 3 (B2 sicher)
  Aufgabenerfüllung: 3 (B2 sicher) — The learner addresses all points of the presentation and the discussion with relevant examples and a clear personal position. ['Ich bin der Meinung, dass jeder einen kleinen Beitrag leisten kann']
  Kohärenz: 3 (B2 sicher) — The contribution is well-structured and uses appropriate connectors to link ideas logically. ['...aber Mülltrennung gibt es noch nicht überall.']
  Wortschatz: 3 (B2 sicher) — The vocabulary is varied and includes topic-specific terms like 'Umweltbewusstsein' or 'Rahmenbedingungen'. ['...und vermeide Plastikverpackungen, so gut es geht.']
  Grammatik: 3 (B2 sicher) — The sentence structures are mostly correct, with only minor errors in prepositional usage or case. ['...dass die Zugfahrt in manche Länder sehr lang und teuer ist']

umwelt_C1 (C1):
  overall: 4 (über B2)
  Aufgabenerfüllung: 4 (über B2) — The learner addresses all points of the presentation and the discussion with high depth and nuanced argumentation. ['ohne politische Weichenstellungen wird sich am Gesamtbild wenig ändern.']
  Kohärenz: 4 (über B2) — The contribution is perfectly structured with sophisticated transitions and a logical flow of ideas. ['Der Vorteil liegt nicht nur in der geringeren Umweltbelastung, sondern auch...']
  Wortschatz: 4 (über B2) — The vocabulary is highly precise, idiomatic, and includes advanced thematic terms like 'Nischendasein' or 'Weichenstellungen'. ['In meinem Heimatland hat das Thema lange ein Nischendasein gefristet']
  Grammatik: 4 (über B2) — The learner uses complex sentence structures and advanced grammatical constructions almost without any errors. ['Solange ein Flug günstiger ist als die Bahnfahrt, darf man...']

FAILURES: ['levels']
make: *** [Makefile:61: score-eval] Error 1
```

## Review (Claude Code fills this in)
- **Verdict:**
- **Notes:**
