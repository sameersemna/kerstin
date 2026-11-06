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
- **Round 1:** Removed the `Konsistenzprüfung` block from `score.md`; added `grammar_errors` verification, error density and grammar ceilings, grammar evidence swapping, `floor(mean)` overall band, the UI grammar-error count, and the eval overall check.
- **Changed files:** Round 1 touched `backend/prompts/score.md`, `backend/kerstin/score.py`, `backend/kerstin/session.py` (`exam_score` fields), `frontend/app.js`, `frontend/style.css`, `scripts/score_eval.py`, `backend/tests/test_score.py`, `backend/tests/test_exam.py`, `docs/PROTOCOL.md`, and this task file. The round-0 files remain as previously committed.
- **How tested:** `make test` → 250 Python tests + 33 Node tests passed. `make lint` → ruff passed. The hold-out test still finds 0 six-word sequences in `score.md`. The final eval is below and every check is PASS.
- **Measurements (if any):** Final eval scoring latency: **p50 5318 ms, max 8439 ms** with `gemma4:26b`; 0 retries. `umwelt_B2` final `orig`: bands `[3, 3, 3, 3]`, overall 3, density 0.5, verified error `"die Zugfahrt in manche Länder"`.
- **Deviations from spec / extra files touched:** All checks pass. The first eval invocation was stopped by the thermal guard at 80 °C after 11 calls; the prompt was unchanged, the GPU was cooled, and the unchanged eval was rerun once; the successful full run is pasted below. The zero-learner-line behavior remains the accepted compatibility exception from round 0. No files outside the allowed list were touched; the pre-existing `.gitignore` change is untouched.
- **New dependencies (+license):** None.
- **Open questions:** None.

### Full `make score-eval` output
```text
.venv/bin/python scripts/score_eval.py
Model: gemma4:26b | seed: 7 | variants: orig, drop, noisy
Cases: 10 | cool_down: 76→70 °C
GPU wohnen_B1 orig attempt 1: 65 °C
wohnen_B1            orig  bands=[2, 2, 2, 1] overall=1 ms=8439 dropped=0 attempt=1 density=6.1 errors=['viele Leute wohnen in große Städte', 'weil dort gibt es mehr Arbeit', 'zum Beispiel man hat Bus', 'in Berlin seit zwei Jahre', 'Am Anfang ich habe kein Wohnung', 'für Familie mit Kinder', 'weil ich mag die Kino', 'vielleicht man kann mit dem Bus fahren', 'mit meine Freunde']
GPU wohnen_B1 drop attempt 1: 72 °C
wohnen_B1            drop  bands=[2, 2, 2, 1] overall=1 ms=7753 dropped=0 attempt=1
GPU wohnen_B1 noisy attempt 1: 73 °C
wohnen_B1            noisy bands=[2, 2, 2, 1] overall=1 ms=8374 dropped=0 attempt=1
GPU wohnen_B2 orig attempt 1: 73 °C
wohnen_B2            orig  bands=[3, 3, 3, 3] overall=3 ms=4927 dropped=0 attempt=1 density=0.5 errors=['Ein großer Nachteil sind allerdings die hohe Mieten']
GPU wohnen_B2 drop attempt 1: 74 °C
wohnen_B2            drop  bands=[3, 3, 3, 3] overall=3 ms=4855 dropped=0 attempt=1
GPU wohnen_B2 noisy attempt 1: 74 °C
wohnen_B2            noisy bands=[3, 3, 3, 3] overall=3 ms=6971 dropped=0 attempt=1
GPU wohnen_C1 orig attempt 1: 75 °C
wohnen_C1            orig  bands=[4, 4, 4, 4] overall=4 ms=4926 dropped=0 attempt=1 density=0.0 errors=[]
GPU wohnen_C1 drop attempt 1: 75 °C
wohnen_C1            drop  bands=[4, 4, 4, 4] overall=4 ms=4670 dropped=1 attempt=1
GPU wohnen_C1 noisy attempt 1: 75 °C
wohnen_C1            noisy bands=[3, 3, 3, 3] overall=3 ms=7057 dropped=0 attempt=1
GPU wohnen_B2_offtask orig attempt 1: 75 °C
wohnen_B2_offtask    orig  bands=[1, 2, 2, 3] overall=2 ms=5747 dropped=0 attempt=1 density=0.0 errors=[]
GPU wohnen_B2_offtask drop attempt 1: 75 °C
wohnen_B2_offtask    drop  bands=[1, 2, 2, 3] overall=2 ms=6713 dropped=0 attempt=1
GPU wohnen_B2_offtask noisy attempt 1: 76 °C
GPU wohnen_B2_offtask noisy attempt 1: 76 °C >= 76 °C, cooling to 70 °C ...
GPU wohnen_B2_offtask noisy attempt 1: 68 °C
GPU wohnen_B2_offtask noisy attempt 1: cooled to 68 °C, continuing
wohnen_B2_offtask    noisy bands=[1, 2, 2, 2] overall=1 ms=5001 dropped=0 attempt=1
GPU medien_B1 orig attempt 1: 74 °C
medien_B1            orig  bands=[2, 2, 2, 1] overall=1 ms=6006 dropped=0 attempt=1 density=5.1 errors=['vielleicht zwei oder drei Stunde', 'man kann mit Familie in mein Land sprechen', 'Einmal ich habe ein Foto gepostet', 'sie verstehen nicht die Gefahr', 'Die Kinder sind sehr schlau mit Handy', 'die Firma muss kontrollieren den Ausweis']
GPU medien_B1 drop attempt 1: 75 °C
medien_B1            drop  bands=[2, 2, 2, 1] overall=1 ms=5634 dropped=0 attempt=1
GPU medien_B1 noisy attempt 1: 74 °C
medien_B1            noisy bands=[2, 2, 2, 1] overall=1 ms=5962 dropped=0 attempt=1
GPU medien_B2 orig attempt 1: 75 °C
medien_B2            orig  bands=[3, 3, 3, 3] overall=3 ms=5160 dropped=0 attempt=1 density=0.5 errors=['in den man offline ist']
GPU medien_B2 drop attempt 1: 75 °C
medien_B2            drop  bands=[3, 3, 3, 3] overall=3 ms=4560 dropped=0 attempt=1
GPU medien_B2 noisy attempt 1: 75 °C
medien_B2            noisy bands=[3, 3, 3, 2] overall=2 ms=5070 dropped=0 attempt=1
GPU medien_C1 orig attempt 1: 75 °C
medien_C1            orig  bands=[4, 4, 4, 4] overall=4 ms=5081 dropped=1 attempt=1 density=0.0 errors=[]
GPU medien_C1 drop attempt 1: 76 °C
GPU medien_C1 drop attempt 1: 76 °C >= 76 °C, cooling to 70 °C ...
GPU medien_C1 drop attempt 1: 68 °C
GPU medien_C1 drop attempt 1: cooled to 68 °C, continuing
medien_C1            drop  bands=[4, 4, 4, 3] overall=3 ms=4899 dropped=1 attempt=1
GPU medien_C1 noisy attempt 1: 74 °C
medien_C1            noisy bands=[3, 3, 3, 3] overall=3 ms=7171 dropped=0 attempt=1
GPU umwelt_B1 orig attempt 1: 74 °C
umwelt_B1            orig  bands=[2, 2, 2, 1] overall=1 ms=5785 dropped=0 attempt=1 density=4.1 errors=['In meinem Land die Leute trennen nicht', 'mit Fahrrad zur Arbeit', 'ich möchte reisen nach Spanien', 'weil da ist warm', 'Ich mag neue Essen probieren']
GPU umwelt_B1 drop attempt 1: 75 °C
umwelt_B1            drop  bands=[2, 2, 2, 1] overall=1 ms=4932 dropped=0 attempt=1
GPU umwelt_B1 noisy attempt 1: 74 °C
umwelt_B1            noisy bands=[2, 2, 2, 1] overall=1 ms=5679 dropped=1 attempt=1
GPU umwelt_B2 orig attempt 1: 75 °C
umwelt_B2            orig  bands=[3, 3, 3, 3] overall=3 ms=5238 dropped=0 attempt=1 density=0.5 errors=['die Zugfahrt in manche Länder']
GPU umwelt_B2 drop attempt 1: 75 °C
umwelt_B2            drop  bands=[3, 3, 3, 3] overall=3 ms=4213 dropped=0 attempt=1
GPU umwelt_B2 noisy attempt 1: 76 °C
GPU umwelt_B2 noisy attempt 1: 76 °C >= 76 °C, cooling to 70 °C ...
GPU umwelt_B2 noisy attempt 1: 68 °C
GPU umwelt_B2 noisy attempt 1: cooled to 68 °C, continuing
umwelt_B2            noisy bands=[3, 3, 3, 2] overall=2 ms=5066 dropped=0 attempt=1
GPU umwelt_C1 orig attempt 1: 74 °C
umwelt_C1            orig  bands=[4, 4, 4, 4] overall=4 ms=5398 dropped=0 attempt=1 density=0.0 errors=[]
GPU umwelt_C1 drop attempt 1: 75 °C
umwelt_C1            drop  bands=[4, 4, 4, 4] overall=4 ms=4673 dropped=0 attempt=1
GPU umwelt_C1 noisy attempt 1: 75 °C
umwelt_C1            noisy bands=[3, 3, 3, 3] overall=3 ms=7274 dropped=0 attempt=1
parse: PASS — 30/30 parsed
order: PASS — wohnen B1=1.75 B2=3.0 C1=4.0; medien B1=1.75 B2=3.0 C1=4.0; umwelt B1=1.75 B2=3.0 C1=4.0
levels: PASS — B1=wohnen_B1:1.75, medien_B1:1.75, umwelt_B1:1.75; B2=wohnen_B2:3.0, medien_B2:3.0, umwelt_B2:3.0; C1=wohnen_C1:4.0, medien_C1:4.0, umwelt_C1:4.0
overall: PASS — wohnen_B1:1; medien_B1:1; umwelt_B1:1; wohnen_B2:3; medien_B2:3; umwelt_B2:3; wohnen_C1:4; medien_C1:4; umwelt_C1:4
offtask: PASS — aufgabe=1/3 wortschatz=2/3 grammatik=3/3
stability: PASS — max criterion spread=1; overall stable in 10/10 cases
evidence: PASS — 4/120 dropped (3.3%)
latency: p50=5318 ms max=8439 ms
retries: 0 calls needed a retry

Orig reasons and evidence

wohnen_B1 (B1):
  overall: 1 (unter B2)
  Aufgabenerfüllung: 2 (B2 knapp) — The learner addresses all points from the card, but the development of arguments and examples is very limited. ['Die Stadt hat viele Vorteile, zum Beispiel man hat Bus']
  Kohärenz: 2 (B2 knapp) — The presentation follows a logical order using simple connectors like 'aber' and 'weil'. ['Aber die Wohnung ist sehr teuer und es ist laut.']
  Wortschatz: 2 (B2 knapp) — The vocabulary is sufficient to cover the topic but remains at a basic, repetitive level. ['In meinem Heimatland viele Leute wohnen in große Städte']
  Grammatik: 1 (unter B2) — There are frequent and recurring errors in basic structures, such as word order and case. ['viele Leute wohnen in große Städte']

wohnen_B2 (B2):
  overall: 3 (B2 sicher)
  Aufgabenerfüllung: 3 (B2 sicher) — The learner addresses all points of the task with clear examples and a personal opinion. ['Meiner Meinung nach ist die Stadt ideal für Studenten und Berufsanfänger.']
  Kohärenz: 3 (B2 sicher) — The presentation is well-structured and uses various connectors to link ideas logically. ['...deshalb habe ich zuerst in einer WG gewohnt...']
  Wortschatz: 3 (B2 sicher) — The vocabulary is appropriate for the topic and includes specific terms like 'Kulturangebot' or 'Busverbindungen'. ['Ein großer Nachteil sind allerdings die hohe Mieten und der Lärm.']
  Grammatik: 3 (B2 sicher) — The sentence structures are mostly correct, though there is a minor error in subject-verb agreement. ['Ein großer Nachteil sind allerdings die hohe Mieten']

wohnen_C1 (C1):
  overall: 4 (über B2)
  Aufgabenerfüllung: 4 (über B2) — The learner addresses all points of the prompt with high complexity and provides a nuanced personal opinion. ['Die Vorteile liegen auf der Hand – kurze Wege, ein dichtes Nahverkehrsnetz']
  Kohärenz: 4 (über B2) — The contribution is logically structured with sophisticated transitions and a clear, continuous flow of thought. ['Dem stehen jedoch erhebliche Nachteile gegenüber']
  Wortschatz: 4 (über B2) — The vocabulary is precise, varied, and includes idiomatic expressions appropriate for a high level. ['...vor allem in bestimmten Lebensphasen attraktiv ist.']
  Grammatik: 4 (über B2) — The learner uses complex sentence structures with almost no identifiable grammatical errors. ['Sobald Faktoren wie Familie oder Ruhe an Bedeutung gewinnen']

wohnen_B2_offtask (B2):
  overall: 2 (B2 knapp)
  Aufgabenerfüllung: 1 (unter B2) — The learner fails to address the required points of the presentation, such as the situation in their home country or advantages/disadvantages of city living, and instead talks about a vacation in Portugal. ['Letztes Jahr war ich im Urlaub in Portugal']
  Kohärenz: 2 (B2 knapp) — The learner uses basic connectors like 'und', 'obwohl', and 'deshalb' to link ideas, but the content lacks a logical connection to the assigned topic. ['obwohl wir kaum Portugiesisch sprechen konnten']
  Wortschatz: 2 (B2 knapp) — The vocabulary is functional and includes some specific terms like 'Busverbindungen' or 'pendeln', but remains largely at a basic level. ['ohne Auto ist es auf dem Land schwierig']
  Grammatik: 3 (B2 sicher) — The grammatical structures are mostly correct, using subordinate clauses and past tense accurately without significant errors. ['Ich würde trotzdem lieber in der Stadt wohnen']

medien_B1 (B1):
  overall: 1 (unter B2)
  Aufgabenerfüllung: 2 (B2 knapp) — The learner addresses all points from the card, but the development of the points is minimal and lacks depth. ['Es gibt Chancen, zum Beispiel man kann mit Familie...']
  Kohärenz: 2 (B2 knapp) — The contribution is logically structured with simple connectors like 'aber' and 'zum Beispiel'. ['Aber es gibt auch Risiken, viele Leute schreiben...']
  Wortschatz: 2 (B2 knapp) — The vocabulary is functional and includes some topic-related words, but remains mostly at a basic level. ['viele Leute schreiben böse Kommentare und man verliert viel Zeit']
  Grammatik: 1 (unter B2) — The basic sentence structures are mostly correct, though there are noticeable errors in word order and verb placement. ['vielleicht zwei oder drei Stunde']

medien_B2 (B2):
  overall: 3 (B2 sicher)
  Aufgabenerfüllung: 3 (B2 sicher) — The learner addresses all points of the card with relevant examples and a clear personal position. ['Soziale Medien bieten viele Chancen, zum Beispiel kann man sich schnell informieren']
  Kohärenz: 3 (B2 sicher) — The presentation is well-structured and uses appropriate connectors to link ideas logically. ['Deshalb habe ich letztes Jahr für einen Monat alle Apps gelöscht']
  Wortschatz: 3 (B2 sicher) — The vocabulary is varied and appropriate for the topic, including terms like 'Falschinformationen' or 'Datenschutz'. ['besonders für Jugendliche. Ich habe selbst gemerkt']
  Grammatik: 3 (B2 sicher) — The sentence structures are mostly correct, with only one minor error in a relative clause. ['in den man offline ist']

medien_C1 (C1):
  overall: 4 (über B2)
  Aufgabenerfüllung: 4 (über B2) — The learner addresses all points of the prompt with high complexity, providing a nuanced personal position and weighing different aspects of the topic. ['Ich plädiere daher nicht für Verzicht, sondern für Medienkompetenz']
  Kohärenz: 4 (über B2) — The contribution is logically structured with sophisticated transitions and a clear, continuous line of thought. [None]
  Wortschatz: 4 (über B2) — The vocabulary is highly precise, idiomatic, and includes advanced thematic terms like 'ambivalente Rolle' or 'Medienkompetenz'. ['Die Chancen sind unbestreitbar – Informationen verbreiten sich in Echtzeit']
  Grammatik: 4 (über B2) — The learner uses complex sentence structures and advanced grammatical constructions almost entirely without errors. ['...ohne sich von ihnen vereinnahmen zu lassen']

umwelt_B1 (B1):
  overall: 1 (unter B2)
  Aufgabenerfüllung: 2 (B2 knapp) — The learner addresses all points from the card, but the development of advantages and disadvantages is very brief. ['Aber Bio-Essen ist teuer, das ist ein Nachteil.']
  Kohärenz: 2 (B2 knapp) — The contribution is logically structured with simple connectors like 'und', 'aber', and 'weil'. ['Ich fahre mit Fahrrad zur Arbeit und ich kaufe keine Plastiktüte.']
  Wortschatz: 2 (B2 knapp) — The vocabulary is functional and includes some topic-related words, but remains mostly at a basic level. ['In meinem Land die Leute trennen nicht den Müll']
  Grammatik: 1 (unter B2) — The basic sentence structures are mostly correct, though there are clear errors in word order and preposition usage. ['In meinem Land die Leute trennen nicht']

umwelt_B2 (B2):
  overall: 3 (B2 sicher)
  Aufgabenerfüllung: 3 (B2 sicher) — The learner addresses all points of the presentation with clear examples and provides a personal opinion. ['Ich bin der Meinung, dass jeder einen kleinen Beitrag leisten kann']
  Kohärenz: 3 (B2 sicher) — The contribution is well-structured and uses appropriate connectors to link ideas logically. ['Das hat Vorteile für die Umwelt und auch für die Gesundheit.']
  Wortschatz: 3 (B2 sicher) — The vocabulary is varied and appropriate for the topic, including terms like 'Rahmenbedingungen' and 'umweltfreundlich'. ['...und vermeide Plastikverpackungen, so gut es geht.']
  Grammatik: 3 (B2 sicher) — The sentence structures are mostly correct, with only minor errors in prepositional usage. ['die Zugfahrt in manche Länder']

umwelt_C1 (C1):
  overall: 4 (über B2)
  Aufgabenerfüllung: 4 (über B2) — The learner addresses all points of the presentation comprehensively and provides a nuanced personal opinion. ['ohne politische Weichenstellungen wird sich am Gesamtbild wenig ändern.']
  Kohärenz: 4 (über B2) — The contribution is logically structured with sophisticated transitions and a clear, coherent flow of ideas. ['Der Vorteil liegt nicht nur in der geringeren Umweltbelastung, sondern auch...']
  Wortschatz: 4 (über B2) — The vocabulary is highly precise, idiomatic, and includes advanced thematic terms like 'Nischendasein' or 'Weichenstellungen'. ['In meinem Heimatland hat das Thema lange ein Nischendasein gefristet']
  Grammatik: 4 (über B2) — The learner uses complex sentence structures with almost no identifiable grammatical errors. ['Ich besitze kein Auto mehr, lege die meisten Strecken mit dem Rad zurück']

All score checks passed.
```

## Review (Claude Code fills this in)
- **Verdict:**
- **Notes:**
- **Verdict:** Changes requested (round 1). Plumbing accepted.
- **Notes:**
  - **What's good:**
    - parser, session order, UI (DOM-only), privacy (no text in logs, no disk writes);
    - 246 Python + 33 Node tests pass, and lint passes;
    - 30/30 parsed, 0 retries;
    - the off-task case is detected;
    - stability holds, 5 % of quotes dropped;
    - p50 4.6 s, which is acceptable at the end of an exam.
  - **Real defect 1 — the overall band is misleading:**
    - every B1 case shows the overall band 2 „B2 knapp“ (median of [2,2,2,1] = 2). A B1 learner is told they are at B2. This is the lead's rule (D022 draft) and it's wrong.
  - **Real defect 2 — grammar is lenient on clear B1 errors:**
    - `medien_B1` and `umwelt_B1` get grammar 2 with "mostly correct". The texts have 6–14 clear errors (verb position after Einmal/In meinem Land/weil, „zwei Stunde“, „mit meine Freunde“, „neue Essen“…).
    - On B2 cases, the grammar evidence often contains no error (`umwelt_B2`: „dass die Zugfahrt in manche Länder…“ is correct; the real slip is „etwas ganz anderes zu sehen“).
  - **Prompt tuned to the calibration set:**
    - the „Konsistenzprüfung“ block caps Aufgabe/Kohärenz when grammar or vocabulary is weak. That couples the criteria (a learner with full task coverage but weak grammar would be told their task fulfilment is weak) and was iterated against the same 10 cases.
    - Calibration cases may not be used for prompt iteration like this; it makes the eval meaningless. The lead will check generalisation with a fresh hold-out set the prompt has never seen, after this round.
  - The zero-learner-line behaviour (empty feedback only, no `exam_score`) is accepted.

### Follow-up (round 1) — required changes
1. **`score.md`:** delete the whole „Konsistenzprüfung vor der Ausgabe“ section; the criteria are scored independently. Add the `grammar_errors` instruction (item 2). No other prompt edits.
2. **Grammar error list** (prompt + `score.py`):
   - The JSON gets a 5th key, `"grammar_errors": ["…", …]`:
     - every clear grammar error in the learner's lines (Kasus, Verbform, Verbstellung, Kongruenz, Präposition, Artikel/Genus);
     - each one a verbatim snippet of ≤ 8 words containing the error;
     - max 15;
     - no style or wording preferences;
     - `[]` if there are none.
   - `parse_score` verifies each snippet verbatim (same normalisation as evidence). Unverified snippets are dropped and counted in `dropped_evidence`. A missing or non-list `grammar_errors` → treat as `[]` and log a parse warning (no failure).
   - `error_density = len(verified) / learner_words * 100`.
   - **Grammar ceiling from density:**
     - ≥ 3.0 → max band 1;
     - ≥ 1.5 → max 2;
     - ≥ 0.5 → max 3;
     - else no cap.
     - Final grammar band = `min(llm_band, ceiling)`.
   - If the final grammar band is ≤ 3 and there are verified errors, the grammar evidence is the first verified error.
   - `exam_score` adds `"error_density"` (1 decimal) and `"grammar_errors"` (the verified list). The UI shows them only as a small line under the grammar row, „Erkannte Grammatikfehler: N“ (no list).
3. **Overall band = `floor(mean of the 4 final bands)`** (not the median). Update `overall_band` and its tests.
4. **Eval:**
   - print `error_density` and the verified error list for every `orig` run;
   - add an `overall` check on `orig`: B1 cases overall = 1; the three on-task B2 cases overall ∈ {2, 3}; C1 cases overall ≥ 3;
   - keep all other checks and thresholds unchanged.
5. **Tests:** the density ceiling (each threshold edge), dropping an unverified grammar snippet, a missing `grammar_errors` → `[]`, the evidence swap for grammar ≤ 3, and `floor(mean)`.
6. Rerun `make score-eval` **once** after the changes and paste it in full. **No further prompt iteration against the calibration cases.** If checks fail, report it; the lead decides after the hold-out run.

Allowed files (round 1): `backend/prompts/score.md`, `backend/kerstin/score.py`, `backend/kerstin/session.py` (the `exam_score` fields only), `frontend/app.js`, `frontend/style.css`, `scripts/score_eval.py`, `backend/tests/test_score.py`, `backend/tests/test_exam.py`, `docs/PROTOCOL.md`, this task file.
