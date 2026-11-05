# T015 — Model comparison for German correctness: qwen3:14b vs gemma4:26b

**Branch:** `task/T015-model-german` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
Produce the evidence for D014: the same scripted conversations (`make persona-eval`) and the same latency bench, run with `qwen3:14b` (current default) and `gemma4:26b`. The lead then judges German correctness from the transcripts and Sameer decides the model. **Kilo doesn't change the default model.**

## Context
- D014 (Open): `qwen3:14b` makes grammar errors in ≈25 % of replies and gives partly wrong correction explanations (T010 review). Prompt tuning didn't fix it.
- Sameer approved loading **only `gemma4:26b`** (already pulled, Q4_K_M, 25.8B, ~18 GB; Ollama reports Apache 2.0). No other models, no pulls.
- Thermal: the T010 eval ran turns back-to-back and reached 78 °C. The machine shuts down at ~84 °C. Hard abort stays at **80 °C** (one reading per turn, and a turn can add several °C). The eval gets a cool-down so it pauses instead of failing.
- Persona prompt: use the current `persona.md` unchanged for both models, so the comparison is fair.

## Spec
1. **Eval: pauses + cool-down + model override** (`scripts/persona_eval.py`):
   - `--pause SECONDS` (default 2.0) between turns.
   - Cool-down before every turn: if GPU ≥ `--cool-at` (default 76 °C), print it, then poll every 5 s until ≤ `--cool-to` (default 70 °C). If it doesn't cool within 5 min, abort (exit 3).
   - Hard abort at ≥ 80 °C stays.
   - `--model NAME` overrides `ollama_model` for this run (in-process settings). Print the model name in the header and summary.
   - Number every Kerstin reply (`[S1-T3]` = scenario 1, turn 3) so the lead can cite them.
   - Default behavior otherwise unchanged.
2. **Bench cool-down:** same `--cool-at` / `--cool-to` logic in `scripts/latency_bench.py`, with defaults that leave current runs unchanged unless the GPU is ≥ 76 °C. Reuse one helper (e.g. in `smoke_test.py`); don't copy-paste.
3. **`think` compatibility:**
   - Check whether Ollama 0.34.2 accepts `"think": false` for `gemma4:26b`.
   - If it rejects it, add support for omitting the key: `llm_think: bool | None = False`, where `None` means don't send `think` (`KERSTIN_LLM_THINK=` empty → None). Add a test in `backend/tests/test_llm.py`.
   - Only touch `llm.py`/`config.py` if this is needed, and report which case applied.
4. **Runs** (seeds 1234 and 99, both models → 4 eval runs, 120 replies total):
   - `make persona-eval EVAL_ARGS="--model qwen3:14b --seed 1234"`, then `--seed 99`, then the same two for `gemma4:26b`.
   - Paired latency: an 8771 server with `KERSTIN_LLM_SEED=1234`, `KERSTIN_PIPER_VOICE_PATH=voices/de_DE-thorsten-medium.onnx`, and `KERSTIN_OLLAMA_MODEL` set to each model in turn. Run `make bench BENCH_ARGS="--runs 2"`.
   - Report p50/p90 for `llm_first_token_ms`, `first_sentence_ms`, `first_audio_ms`, the VAD-tail estimate, and the early-clause rate (first reply chunk ends in `,` `;` `:` `–`).
   - Run a cold start for `gemma4:26b` only if it happens to be unloaded. Don't force-unload.
   - Record `ollama ps` (size, processor) while each model is loaded, plus the GPU temperatures.
5. **Report:**
   - Paste all 4 eval outputs in full, plus a summary table per model (codes, mean sentences/words) and the bench tables.
   - **Don't grade German correctness yourself.** The lead does that from the transcripts. You may list anything that looks odd, marked as "unverified".

## Hard rules
Port 8771 only; leave 8770 alone. No Whisper `/load`, no Ollama config changes, no model pulls, no models other than `qwen3:14b` and `gemma4:26b`, no force-unload. Thermal: cool-down as above, hard abort 80 °C. Don't change the default model, `persona.md`, or the scenarios.

## Files allowed to change
- `scripts/persona_eval.py`, `scripts/latency_bench.py`, `scripts/smoke_test.py` (shared thermal helper only)
- `backend/kerstin/llm.py`, `backend/kerstin/config.py`, `backend/tests/test_llm.py`, `.env.example`: **only** if step 3 requires it
- this task file (Worker report only)

## Out of scope
Changing the default model (Sameer decides after review), prompt changes, feedback model (T011), any other candidate model.

## Acceptance criteria
- [ ] `make test` and `make lint` pass
- [ ] Eval has `--pause`, cool-down and `--model`; replies are numbered; default run still works
- [ ] 4 eval runs complete (2 seeds × 2 models, 30 replies each), 0 errors, never ≥ 80 °C; cool-down events (if any) visible in the output
- [ ] Paired bench for both models with p50/p90 tables
- [ ] Report contains every transcript in full and the step-3 `think` finding
- [ ] `git diff main --stat` shows only allowed files; default model unchanged

## Worker report (Kilo Code fills this in)
- **Changed files:**
  - `scripts/smoke_test.py` — added the shared async `cool_down(label, cool_at, cool_to)` helper: prints the GPU temperature, hard-aborts at 80 °C, and above `cool_at` polls every 5 s until `cool_to` (5 min timeout → `ThermalAbort`, exit 3). `thermal_guard` is unchanged for the smoke test.
  - `scripts/persona_eval.py` — `--pause` (default 2.0 s), `--cool-at` / `--cool-to` (76/70), `--model` override, header/summary model line, cool-down before every turn, and `[Sx-Ty]` numbering for every Kerstin reply.
  - `scripts/latency_bench.py` — `--cool-at` / `--cool-to` and the same shared cool-down before every warm-up/measured turn and at start/end; default behaviour is otherwise unchanged.
  - `docs/tasks/T015-model-german.md` — Worker report only.
  - **Step 3 did not require code changes**: `think: false` is accepted by Ollama 0.34.2 for `gemma4:26b`. `llm.py`, `config.py`, `tests/test_llm.py` and `.env.example` are untouched.
  - Default model (`qwen3:14b`), `persona.md` and the scenarios are untouched.
- **How tested:**
  - `make test` → 53 passed; `make lint` → `All checks passed!`.
  - Step 3: one direct `/api/chat` request with `"think": false`; result below.
  - Four full eval runs: `--model qwen3:14b --seed 1234`, `--seed 99`, `--model gemma4:26b --seed 1234`, `--seed 99` (30 replies each, 120 total, 0 errors).
  - Default-behaviour check: one 6-reply scenario with **no** new flags (default model `qwen3:14b`, default pause and cool-down); passed.
  - Cool-down check: one 6-reply scenario with `--cool-at 58 --cool-to 55`; the helper cooled and continued (excerpt below).
  - Paired bench on 8771, fixed `KERSTIN_LLM_SEED=1234`, `thorsten-medium`, `--runs 2` per model; 20 measured turns each.
  - Thermal: all 4 required eval runs stayed ≤ 65 °C (no cool-down event was needed because the 2 s pauses kept it below 76); the benches stayed ≤ 67 °C (qwen) and ≤ 62 °C (gemma). Never ≥ 80 °C.
  - No Whisper `/load`, no Ollama config changes, no pulls, no force-unload, no models other than `qwen3:14b` and `gemma4:26b`. 8770 was never started or touched.
  - No eval output files written; the transcripts are only in this report.
- **Measurements (if any):**
  - **Step 3:** HTTP 200 with `"think": false`; cold load took 14.47 s (`load_duration` in the response). No omission logic needed.
  - **Eval summary (2 seeds × 30 = 60 replies per model):**

    | code | qwen3:14b | gemma4:26b |
    |---|---|---|
    | too_long | 8 | 5 |
    | no_question (informational) | 3 | 0 |
    | markdown_or_emoji | 7 | 0 |
    | digits | 0 | 0 |
    | english | 0 | 0 |
    | correction (total) | 1 (the explicitly allowed request) | 0 |
    | non-allowed correction (c) | none | none |
    | mean sentences/reply | 2.99 | 2.89 |
    | mean words/reply | 23.42 | 31.45 |
    | replies | 60 | 60 |

  - **Paired bench (p50 / p90, n=20):**

    | metric | qwen3:14b | gemma4:26b |
    |---|---|---|
    | `llm_first_token_ms` | 840 / 1338 | 908 / 1247 |
    | `first_sentence_ms` | 1448 / 1951 | 1160 / 1467 |
    | `first_audio_ms` | 1630 / 2171 | 1384 / 1661 |
    | VAD-tail estimate (first_audio + 768 ms) | 2398 / 2939 | 2152 / 2429 |
    | early first clause | 2/20 (10 %) | 6/20 (30 %) |

  - Early-clause examples from the bench `(d)` replies (computed by replaying `SentenceSplitter(first_clause_min_words=4)` on the joined reply, as in T006): qwen “Natürlich! Ich lerne oft durch Filme oder Bücher –” (twice); gemma “Das klingt richtig entspannt,”, “Ich gehe sehr gerne bouldern,”, “Hamburg finde ich auch toll,”, “Das klingt nach einem perfekten Weg,”, “Das ist eine gute Frage,”.
  - **GPU:** eval qwen 55→64 °C and 63→65 °C; eval gemma 64→62 °C and 61→62 °C; bench qwen 61→66 °C (max 67); bench gemma 61→61 °C (max 62). Cool-down check: 58 °C ≥ 58 → 56, 56, 55 °C, then continued.
  - **`ollama ps`:** `qwen3:14b` 9.8 GB, 100 % GPU, context 8192; `gemma4:26b` 17 GB, 100 % GPU, context 8192. Both were resident during the benches; other consumers' `codellama:7b`/`bge-m3` rows also appeared at times.
  - **Cold start:** `gemma4:26b` was unloaded when the think check ran; that request loaded it cold in 14.5 s. It was unloaded again before the gemma eval, whose warm-up reloaded it. No force-unload was used.
- **Deviations from spec / extra files touched:**
  - Step 3 needed no change; the allowed `llm.py`/`config.py`/`test_llm.py`/`.env.example` edits were not made.
  - The four required eval runs never reached the 76 °C cool-at threshold (the 2 s pause was enough), so they contain no cool-down event. A separate 6-reply check with `--cool-at 58 --cool-to 55` exercised and shows the cool-down; a default 6-reply check verifies the no-flag path. Both extra checks are outside the 120 required replies.
  - The early-clause rate is derived from the bench `(d)` replies with the splitter, because the bench joins reply chunks into one line (same method as T006).
  - The bench server was started with the medium Piper voice explicitly (`KERSTIN_PIPER_VOICE_PATH=voices/de_DE-thorsten-medium.onnx`) because the local `.env` still points at high; the benchmark is TTS-server-side and both models used medium. The eval uses `NoTTS`.
  - No other files touched.
- **New dependencies (+license):** None.
- **Open questions:**
  - Sameer/Claude judge the German from the full transcripts; no default model change was made here.
  - The eval’s cool-down did not trigger under the 2 s-pause load; if a forced cool-down proof is wanted, re-run with a lower `--cool-at`, as done in the mechanism check.
  - Unverified, not a grammar judgement: in the bench’s second pass, gemma4:26b often begins with “Das hast du mir ja schon vorhin erzählt”, while qwen3:14b’s bench replies are verbatim identical across passes. The eval transcripts above are the primary evidence.

### Step 3 — `think: false` for `gemma4:26b`

```text
seconds: 14.8
status: 200
body: {"model":"gemma4:26b","created_at":"2026-11-05T07:35:26.071935684Z","message":{"role":"assistant","content":"Hallo!"},"done":true,"done_reason":"stop","total_duration":14777317675,"load_duration":14467731415,"prompt_eval_count":17,"prompt_eval_cached_count":0,"prompt_eval_duration":241593000,"eval_count":3,"eval_duration":66019999}
```

Accepted (HTTP 200, content “Hallo!”); no `llm.py`/`config.py`/test change was needed.

### `ollama ps` while both models were resident

```text
NAME          ID              SIZE      PROCESSOR    CONTEXT    UNTIL              
qwen3:14b     bdbd181c33f2    9.8 GB    100% GPU     8192       9 minutes from now    
gemma4:26b    5571076f3d70    17 GB     100% GPU     8192       8 minutes from now
```

### Eval run 1 — `qwen3:14b`, seed 1234

```text
.venv/bin/python scripts/persona_eval.py --model qwen3:14b --seed 1234

Model: qwen3:14b | seed: 1234
GPU at start: 55 °C

=== freies_gespraech ===
Kerstin [S1-T0]: Hey, schön, dass es heute klappt! Ich habe gerade einen Flat White bestellt. Wie war deine Woche bisher?
GPU before S1-T1: 55 °C
Lernende [S1-T1]: Ich wohne seit drei Jahren in Berlin und fühle mich hier schon zu Hause.
Kerstin [S1-T1]: Das ist großartig! Berlin ist eine tolle Stadt, aber man braucht Zeit, um sich einzuleben. Magst du schon bestimmte Bezirke besonders gerne?  [codes: -]
GPU before S1-T2: 56 °C
Lernende [S1-T2]: Ich habe gestern mit ein Freund ins Kino gegangen, aber der Film war langweilig.
Kerstin [S1-T2]: Das tut leid! Was habt ihr euch denn angesehen? Manchmal sind die Werbespots besser als der Film selbst.  [codes: -]
GPU before S1-T3: 57 °C
Lernende [S1-T3]: Weil ich diese Woche viel gearbeitet habe, ich bin am Wochenende ziemlich müde.
Kerstin [S1-T3]: Das klingt anstrengend! Hast du am Wochenende schon etwas geplant, um dich etwas auszuruhen?  [codes: -]
GPU before S1-T4: 57 °C
Lernende [S1-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S1-T4]: Kein Problem! „Deadline“ sagt man auf Deutsch „Frist“. Hast du eine Frist für eine Arbeit oder ein Projekt?  [codes: -]
GPU before S1-T5: 60 °C
Lernende [S1-T5]: Ich wohne seit drei Jahren in Berlin und fühle mich hier schon zu Hause.
Kerstin [S1-T5]: Das ist großartig! Berlin ist eine tolle Stadt, aber man braucht Zeit, um sich einzuleben. Magst du schon bestimmte Bezirke besonders gerne?  [codes: -]
GPU before S1-T6: 60 °C
Lernende [S1-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich freue mich auf der Sommer.
Kerstin [S1-T6]: Natürlich! Die korrekte Form ist: **„Ich freue mich auf den Sommer.“** Das Wort „auf“ benötigt in diesem Satz den Akkusativ, also „den Sommer“. Magst du noch ein Beispiel dazu hören?  [codes: markdown_or_emoji]

=== wg_alltag ===
Kerstin [S2-T0]: Du, hast du kurz Zeit? Ich wollte mal über die Küche reden. Heute Morgen stand wieder alles voll mit Geschirr.
GPU before S2-T1: 61 °C
Lernende [S2-T1]: Ich finde, wir sollten den Putzplan einmal zusammen durchgehen und fair aufteilen.
Kerstin [S2-T1]: Das ist eine gute Idee! Vielleicht können wir auch Regeln für die Küche besprechen, damit alles besser organisiert wird. Hast du schon mal einen Plan gesehen, der funktioniert?  [codes: -]
GPU before S2-T2: 62 °C
Lernende [S2-T2]: Ich habe gestern die Küche geputzt, aber danach hat mein Mitbewohner sein Geschirr wieder auf der Tisch gestellt.
Kerstin [S2-T2]: Das ist ärgerlich! Vielleicht sollten wir eine Regel machen, dass niemand Geschirr einfach wegschafft, sondern es in die Spüle stellt. Hast du das schon mal versucht, zu sagen?  [codes: -]
GPU before S2-T3: 64 °C
Lernende [S2-T3]: Weil die Küche oft unordentlich ist, ich möchte nicht mehr allein putzen.
Kerstin [S2-T3]: Das verstehe ich gut! Es ist mühsam, immer alles allein zu machen. Vielleicht sollten wir auch eine Liste machen, wer wann was putzt. Willst du das übernehmen?  [codes: too_long]
GPU before S2-T4: 63 °C
Lernende [S2-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S2-T4]: Das ist kein Problem! „Deadline“ sagt man auf Deutsch „Frist“. Hast du eine Frist für etwas?  [codes: -]
GPU before S2-T5: 63 °C
Lernende [S2-T5]: Ich finde, wir sollten den Putzplan einmal zusammen durchgehen und fair aufteilen.
Kerstin [S2-T5]: Das ist eine gute Idee! Vielleicht können wir auch Regeln für die Küche besprechen, damit alles besser organisiert wird. Hast du schon mal einen Plan gesehen, der funktioniert?  [codes: -]
GPU before S2-T6: 63 °C
Lernende [S2-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich habe die Küche geputzt, aber danach hat mein Mitbewohner sein Geschirr wieder auf der Tisch gestellt.
Kerstin [S2-T6]: Dein Satz ist fast richtig! Nur „auf der Tisch“ sollte „auf den Tisch“ sein. So ist der Satz korrekt: „Ich habe die Küche geputzt, aber danach hat mein Mitbewohner sein Geschirr wieder auf den Tisch gestellt.“ Gut gemacht! 😊  [codes: too_long, no_question, markdown_or_emoji]

=== arbeit_kollegen ===
Kerstin [S3-T0]: Puh, endlich Mittagspause. Hast du schon gehört, dass ab nächstem Monat nur noch zwei Tage Homeoffice erlaubt sind?
GPU before S3-T1: 64 °C
Lernende [S3-T1]: Ich finde die neuen Homeoffice-Regeln eigentlich ganz sinnvoll, aber zwei Tage sind vielleicht etwas wenig.
Kerstin [S3-T1]: Ich weiß, es ist ein bisschen wenig. Ich selbst arbeite aber immer noch drei Tage im Büro – das ist zumindest bei uns so. Wie sieht es bei euch aus?  [codes: -]
GPU before S3-T2: 64 °C
Lernende [S3-T2]: Ich habe gestern mit mein Chef über das neue Projekt gesprochen, aber er war nicht zufrieden.
Kerstin [S3-T2]: Das klingt schwierig. Was hat er denn nicht gefallen? Und hast du noch Zeit, das zu ändern?  [codes: -]
GPU before S3-T3: 63 °C
Lernende [S3-T3]: Weil das Projekt nächste Woche startet, ich muss am Wochenende noch viel vorbereiten.
Kerstin [S3-T3]: Oh, das klingt stressig! Hast du Hilfe von Kollegen? Ich mache manchmal auch viel am Wochenende, wenn es nötig ist.  [codes: -]
GPU before S3-T4: 63 °C
Lernende [S3-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S3-T4]: Das Wort für „deadline“ ist „Frist“ oder „Termin“. Meistens sagt man aber „Frist“ in solchen Situationen.  [codes: no_question]
GPU before S3-T5: 63 °C
Lernende [S3-T5]: Ich finde die neuen Homeoffice-Regeln eigentlich ganz sinnvoll, aber zwei Tage sind vielleicht etwas wenig.
Kerstin [S3-T5]: Ich weiß, es ist ein bisschen wenig. Ich selbst arbeite aber immer noch drei Tage im Büro – das ist zumindest bei uns so. Wie sieht es bei euch aus?  [codes: -]
GPU before S3-T6: 63 °C
Lernende [S3-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich habe gestern mit mein Chef über das Projekt gesprochen.
Kerstin [S3-T6]: Ja, du hast recht, dass Satz nicht ganz korrekt ist. Es sollte heißen: **„Ich habe gestern mit meinem Chef über das Projekt gesprochen.“** Das Subjekt „mein Chef“ muss mit einem Artikel stehen – also „meinem Chef“. Gut erkannt!  [codes: no_question, markdown_or_emoji, correction]

=== diskussion ===
Kerstin [S4-T0]: Ich habe gestern einen Artikel gelesen: Berlin will die Innenstadt bis 2030 fast autofrei machen. Ehrlich gesagt finde ich das ziemlich übertrieben. Was denkst du?
GPU before S4-T1: 64 °C
Lernende [S4-T1]: Ich finde, man sollte die Innenstadt nicht komplett autofrei machen, sondern zuerst den öffentlichen Verkehr verbessern.
Kerstin [S4-T1]: Das ist ein guter Punkt! Ich stimme zu, dass besserer ÖPNV wichtig ist. Aber denkst du nicht, dass weniger Autos auch die Luft und das Stadtbild verbessern würde?  [codes: -]
GPU before S4-T2: 64 °C
Lernende [S4-T2]: Meiner Meinung nach, die Autos sind nicht das größte Problem, sondern der viele Lieferverkehr.
Kerstin [S4-T2]: Das ist interessant! Ich habe nicht daran gedacht, dass Lieferfahrzeuge so einen Einfluss haben. Wie sieht es in deiner Stadt aus?  [codes: -]
GPU before S4-T3: 64 °C
Lernende [S4-T3]: Ich habe letztes Jahr in Kopenhagen gesehen, wie gut das mit die Fahrräder funktioniert hat.
Kerstin [S4-T3]: Das klingt toll! Kopenhagen ist ja bekannt für ihre Fahrradwege. Hast du selbst oft mit dem Fahrrad gefahren?  [codes: -]
GPU before S4-T4: 64 °C
Lernende [S4-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S4-T4]: Das Wort für „deadline“ ist „Frist“ oder „Deadline“ – manchmal sagt man auch „Abgabetermin“. Was genau meinst du damit?  [codes: -]
GPU before S4-T5: 64 °C
Lernende [S4-T5]: Ich finde, man sollte die Innenstadt nicht komplett autofrei machen, sondern zuerst den öffentlichen Verkehr verbessern.
Kerstin [S4-T5]: Das ist ein guter Punkt! Ich stimme zu, dass besserer ÖPNV wichtig ist. Aber denkst du nicht, dass weniger Autos auch die Luft und das Stadtbild verbessern würde?  [codes: -]
GPU before S4-T6: 64 °C
Lernende [S4-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Meiner Meinung nach, die Autos sind nicht das größte Problem.
Kerstin [S4-T6]: Dein Satz ist fast richtig. Es heißt: „Meiner Meinung nach sind die Autos nicht das größte Problem.“ Hast du das so gemeint?  [codes: -]

=== pruefung_planung ===
Kerstin [S5-T0]: Also, wir sollen die Abschiedsfeier für Frau Becker planen. Was meinst du, wo könnten wir feiern?
GPU before S5-T1: 64 °C
Lernende [S5-T1]: Ich schlage vor, dass wir die Feier im Kursraum machen, weil das am günstigsten ist.
Kerstin [S5-T1]: Das ist eine gute Idee! Dann sparen wir Geld für das Essen. Hast du schon einen Termin im Kopf?  [codes: -]
GPU before S5-T2: 64 °C
Lernende [S5-T2]: Ich denke, wir sollten das Geschenk zusammen kaufen, weil es ist persönlicher.
Kerstin [S5-T2]: Das ist ein sehr schöner Vorschlag! Wie viel Geld können wir ungefähr für das Geschenk zusammennehmen?  [codes: -]
GPU before S5-T3: 63 °C
Lernende [S5-T3]: Für die Einladungen könnte ich am Wochenende schreiben, wenn ihr mir die Namen geben.
Kerstin [S5-T3]: Das wäre gut! Ich schreibe dann die Namen auf, wenn ich zu Hause bin. Was meinst du zu dem Termin am Freitagabend?  [codes: -]
GPU before S5-T4: 64 °C
Lernende [S5-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S5-T4]: Das Wort „Deadline“ sagt man auf Deutsch „Frist“. Hast du eine Frist für die Einladungen?  [codes: -]
GPU before S5-T5: 64 °C
Lernende [S5-T5]: Ich schlage vor, dass wir die Feier im Kursraum machen, weil das am günstigsten ist.
Kerstin [S5-T5]: Das ist eine gute Idee! Dann sparen wir Geld für das Essen. Hast du schon einen Termin im Kopf?  [codes: -]
GPU before S5-T6: 63 °C
Lernende [S5-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich denke, wir sollten das Geschenk zusammen kaufen, weil es ist persönlicher.
Kerstin [S5-T6]: Dein Satz ist fast richtig. Es sollte heißen: **„… weil es persönlicher ist.“** So klingt es natürlicher. Willst du noch etwas anderes üben?  [codes: too_long, markdown_or_emoji]
GPU at end: 64 °C

(b) Summary
model: qwen3:14b
code                 count
--------------------------
too_long                 3
no_question              3
markdown_or_emoji        4
digits                   0
english                  0
correction               1

total replies: 30
mean sentences/reply: 2.97
mean words/reply: 23.03
GPU: start 55 °C, end 64 °C

(c) correction flagged where not allowed
none
```

### Eval run 2 — `qwen3:14b`, seed 99

```text
.venv/bin/python scripts/persona_eval.py --model qwen3:14b --seed 99

Model: qwen3:14b | seed: 99
GPU at start: 63 °C

=== freies_gespraech ===
Kerstin [S1-T0]: Hey, schön, dass es heute klappt! Ich habe gerade einen Flat White bestellt. Wie war deine Woche bisher?
GPU before S1-T1: 63 °C
Lernende [S1-T1]: Ich wohne seit drei Jahren in Berlin und fühle mich hier schon zu Hause.
Kerstin [S1-T1]: Das ist großartig! Berlin ist eine tolle Stadt, aber man braucht Zeit, um sich richtig einzuleben. Magst du hier besonders etwas?  [codes: -]
GPU before S1-T2: 63 °C
Lernende [S1-T2]: Ich habe gestern mit ein Freund ins Kino gegangen, aber der Film war langweilig.
Kerstin [S1-T2]: Schade, dass der Film nicht gut war. Mit wem bist du ins Kino gegangen? Hast du noch andere Pläne für diesen Abend?  [codes: -]
GPU before S1-T3: 64 °C
Lernende [S1-T3]: Weil ich diese Woche viel gearbeitet habe, ich bin am Wochenende ziemlich müde.
Kerstin [S1-T3]: Das verstehe ich – wenn man viel arbeitet, ist es wichtig, sich am Wochenende auszuruhen. Hast du etwas Geplantes, um dich zu erholen?  [codes: -]
GPU before S1-T4: 64 °C
Lernende [S1-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S1-T4]: Das Wort „Deadline“ heißt auf Deutsch „Frist“. Hast du eine Frist für eine Arbeit?  [codes: -]
GPU before S1-T5: 64 °C
Lernende [S1-T5]: Ich wohne seit drei Jahren in Berlin und fühle mich hier schon zu Hause.
Kerstin [S1-T5]: Das ist großartig! Berlin ist eine tolle Stadt, aber man braucht Zeit, um sich richtig einzuleben. Magst du hier besonders etwas?  [codes: -]
GPU before S1-T6: 64 °C
Lernende [S1-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich freue mich auf der Sommer.
Kerstin [S1-T6]: Dein Satz ist fast richtig, aber „auf der Sommer“ ist nicht korrekt. Du meinst wahrscheinlich: **„Ich freue mich auf den Sommer.“** Möchtest du wissen, warum „den“ hier richtig ist?  [codes: markdown_or_emoji]

=== wg_alltag ===
Kerstin [S2-T0]: Du, hast du kurz Zeit? Ich wollte mal über die Küche reden. Heute Morgen stand wieder alles voll mit Geschirr.
GPU before S2-T1: 64 °C
Lernende [S2-T1]: Ich finde, wir sollten den Putzplan einmal zusammen durchgehen und fair aufteilen.
Kerstin [S2-T1]: Das ist eine gute Idee! Vielleicht können wir auch Regeln für die Küche machen, zum Beispiel, wer am Abend spült. Was denkst du?  [codes: -]
GPU before S2-T2: 64 °C
Lernende [S2-T2]: Ich habe gestern die Küche geputzt, aber danach hat mein Mitbewohner sein Geschirr wieder auf der Tisch gestellt.
Kerstin [S2-T2]: Das ist ärgerlich! Vielleicht sollten wir auch besprechen, dass niemand Geschirr einfach auf den Tisch stellt. Hast du schon mal mit ihm darüber gesprochen?  [codes: -]
GPU before S2-T3: 64 °C
Lernende [S2-T3]: Weil die Küche oft unordentlich ist, ich möchte nicht mehr allein putzen.
Kerstin [S2-T3]: Das verstehe ich! Es ist nicht fair, immer nur du putzt. Vielleicht können wir auch eine Liste mit Aufgaben machen, die jeder abwechselnd macht. Was meinst du?  [codes: too_long]
GPU before S2-T4: 64 °C
Lernende [S2-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S2-T4]: Das ist kein Problem! „Deadline“ heißt auf Deutsch „Frist“. Hast du eine Frist für die Putzplan-Unterredung?  [codes: -]
GPU before S2-T5: 64 °C
Lernende [S2-T5]: Ich finde, wir sollten den Putzplan einmal zusammen durchgehen und fair aufteilen.
Kerstin [S2-T5]: Das ist eine gute Idee! Vielleicht können wir auch Regeln für die Küche machen, zum Beispiel, wer am Abend spült. Was denkst du?  [codes: -]
GPU before S2-T6: 64 °C
Lernende [S2-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich habe die Küche geputzt, aber danach hat mein Mitbewohner sein Geschirr wieder auf der Tisch gestellt.
Kerstin [S2-T6]: Dein Satz ist schon gut! Nur: „auf der Tisch“ sollte „auf den Tisch“ heißen. Hast du noch andere Sätze, die du gerne korrigieren lassen möchtest?  [codes: -]

=== arbeit_kollegen ===
Kerstin [S3-T0]: Puh, endlich Mittagspause. Hast du schon gehört, dass ab nächstem Monat nur noch zwei Tage Homeoffice erlaubt sind?
GPU before S3-T1: 64 °C
Lernende [S3-T1]: Ich finde die neuen Homeoffice-Regeln eigentlich ganz sinnvoll, aber zwei Tage sind vielleicht etwas wenig.
Kerstin [S3-T1]: Das stimme ich zu – zwei Tage fühlen sich für mich auch etwas kurz an. Wie sieht es bei dir aus? Arbeitest du häufig von zu Hause aus?  [codes: -]
GPU before S3-T2: 64 °C
Lernende [S3-T2]: Ich habe gestern mit mein Chef über das neue Projekt gesprochen, aber er war nicht zufrieden.
Kerstin [S3-T2]: Das klingt schwierig. Warum war er nicht zufrieden? Hast du das Gefühl, dass du mehr erklären musst?  [codes: -]
GPU before S3-T3: 64 °C
Lernende [S3-T3]: Weil das Projekt nächste Woche startet, ich muss am Wochenende noch viel vorbereiten.
Kerstin [S3-T3]: Das klingt stressig! Hast du Hilfe von Kollegen oder deiner Chefin bekommen? Ich weiß, wie es ist, wenn die Zeit knapp wird.  [codes: -]
GPU before S3-T4: 64 °C
Lernende [S3-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S3-T4]: Das ist kein Problem! Das Wort für „deadline“ auf Deutsch ist „Frist“. Hast du eine Frist für dein Projekt?  [codes: -]
GPU before S3-T5: 64 °C
Lernende [S3-T5]: Ich finde die neuen Homeoffice-Regeln eigentlich ganz sinnvoll, aber zwei Tage sind vielleicht etwas wenig.
Kerstin [S3-T5]: Das stimme ich zu – zwei Tage fühlen sich für mich auch etwas kurz an. Wie sieht es bei dir aus? Arbeitest du häufig von zu Hause aus?  [codes: -]
GPU before S3-T6: 64 °C
Lernende [S3-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich habe gestern mit mein Chef über das Projekt gesprochen.
Kerstin [S3-T6]: Natürlich! Deine Satz ist fast richtig. Es sollte heißen: **„Ich habe gestern mit meinem Chef über das Projekt gesprochen.“** Du brauchst den Artikel **„meinem“** vor **„Chef“**. Willst du noch mehr Beispiele üben?  [codes: too_long, markdown_or_emoji]

=== diskussion ===
Kerstin [S4-T0]: Ich habe gestern einen Artikel gelesen: Berlin will die Innenstadt bis 2030 fast autofrei machen. Ehrlich gesagt finde ich das ziemlich übertrieben. Was denkst du?
GPU before S4-T1: 65 °C
Lernende [S4-T1]: Ich finde, man sollte die Innenstadt nicht komplett autofrei machen, sondern zuerst den öffentlichen Verkehr verbessern.
Kerstin [S4-T1]: Das ist eine gute Idee! Ich persönlich nutze den ÖPNV viel, aber ich weiß, dass nicht jeder das kann. Wie sieht es bei dir aus? Fährst du oft mit dem Bus oder der U-Bahn?  [codes: too_long]
GPU before S4-T2: 65 °C
Lernende [S4-T2]: Meiner Meinung nach, die Autos sind nicht das größte Problem, sondern der viele Lieferverkehr.
Kerstin [S4-T2]: Das ist ein interessanter Punkt! Ich habe auch oft Lastwagen gesehen, besonders in der Innenstadt. Hast du eine Lösung dafür?  [codes: -]
GPU before S4-T3: 65 °C
Lernende [S4-T3]: Ich habe letztes Jahr in Kopenhagen gesehen, wie gut das mit die Fahrräder funktioniert hat.
Kerstin [S4-T3]: Kopenhagen ist ja bekannt für ihre Fahrradwege! Hast du selbst schon mal mit dem Fahrrad in der Stadt unterwegs gewesen?  [codes: -]
GPU before S4-T4: 65 °C
Lernende [S4-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S4-T4]: Das Wort für „deadline“ ist „Frist“ oder „Termin“. Meistens sagt man „Frist“ in beruflichen Situationen. Hast du eine Frist für deine Arbeit?  [codes: -]
GPU before S4-T5: 65 °C
Lernende [S4-T5]: Ich finde, man sollte die Innenstadt nicht komplett autofrei machen, sondern zuerst den öffentlichen Verkehr verbessern.
Kerstin [S4-T5]: Das ist eine gute Idee! Ich persönlich nutze den ÖPNV viel, aber ich weiß, dass nicht jeder das kann. Wie sieht es bei dir aus? Fährst du oft mit dem Bus oder der U-Bahn?  [codes: too_long]
GPU before S4-T6: 65 °C
Lernende [S4-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Meiner Meinung nach, die Autos sind nicht das größte Problem.
Kerstin [S4-T6]: Dein Satz ist fast richtig! Es heißt: **„Meiner Meinung nach sind die Autos nicht das größte Problem.“** Du vergisst das **„sind“**. Willst du noch mehr Übung?  [codes: markdown_or_emoji]

=== pruefung_planung ===
Kerstin [S5-T0]: Also, wir sollen die Abschiedsfeier für Frau Becker planen. Was meinst du, wo könnten wir feiern?
GPU before S5-T1: 65 °C
Lernende [S5-T1]: Ich schlage vor, dass wir die Feier im Kursraum machen, weil das am günstigsten ist.
Kerstin [S5-T1]: Das ist eine gute Idee! Wir sparen Geld, und alle wissen, wo es ist. Hast du schon einen Termin im Kopf?  [codes: -]
GPU before S5-T2: 65 °C
Lernende [S5-T2]: Ich denke, wir sollten das Geschenk zusammen kaufen, weil es ist persönlicher.
Kerstin [S5-T2]: Das ist ein sehr nettes Vorschlag! Dann können wir gemeinsam etwas Besonderes finden. Was hältst du von einem Kochbuch, wenn sie gerne kocht?  [codes: -]
GPU before S5-T3: 65 °C
Lernende [S5-T3]: Für die Einladungen könnte ich am Wochenende schreiben, wenn ihr mir die Namen geben.
Kerstin [S5-T3]: Das wäre prima! Bitte schick mir die Namen, dann kann ich loslegen. Hast du schon eine Idee, wer alles kommen wird?  [codes: -]
GPU before S5-T4: 65 °C
Lernende [S5-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S5-T4]: Das Wort für „deadline“ auf Deutsch ist „Frist“. Hast du eine Frist, bis wann du die Einladungen fertig haben möchtest?  [codes: -]
GPU before S5-T5: 65 °C
Lernende [S5-T5]: Ich schlage vor, dass wir die Feier im Kursraum machen, weil das am günstigsten ist.
Kerstin [S5-T5]: Das ist eine gute Idee! Wir sparen Geld, und alle wissen, wo es ist. Hast du schon einen Termin im Kopf?  [codes: -]
GPU before S5-T6: 65 °C
Lernende [S5-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich denke, wir sollten das Geschenk zusammen kaufen, weil es ist persönlicher.
Kerstin [S5-T6]: Dein Satz ist gut verständlich, aber „weil es ist persönlicher“ klingt ein bisschen ungewöhnlich. Du könntest sagen: „…weil es persönlicher ist.“ Oder noch natürlicher: „…weil wir so etwas Persönlicheres finden können.“ Möchtest du noch andere Sätze korrigieren lassen?  [codes: too_long]
GPU at end: 65 °C

(b) Summary
model: qwen3:14b
code                 count
--------------------------
too_long                 5
no_question              0
markdown_or_emoji        3
digits                   0
english                  0
correction               0

total replies: 30
mean sentences/reply: 3.00
mean words/reply: 23.80
GPU: start 63 °C, end 65 °C

(c) correction flagged where not allowed
none
```

### Eval run 3 — `gemma4:26b`, seed 1234

```text
.venv/bin/python scripts/persona_eval.py --model gemma4:26b --seed 1234

Model: gemma4:26b | seed: 1234
GPU at start: 64 °C

=== freies_gespraech ===
Kerstin [S1-T0]: Hey, schön, dass es heute klappt! Ich habe gerade einen Flat White bestellt. Wie war deine Woche bisher?
GPU before S1-T1: 64 °C
Lernende [S1-T1]: Ich wohne seit drei Jahren in Berlin und fühle mich hier schon zu Hause.
Kerstin [S1-T1]: Das ist ja toll, dass du dich hier schon so wohlfühlst. Ich lebe erst seit zwei Jahren hier und finde die Stadt manchmal noch ein bisschen stressig. In welchem Stadtteil wohnst du denn?  [codes: -]
GPU before S1-T2: 63 °C
Lernende [S1-T2]: Ich habe gestern mit ein Freund ins Kino gegangen, aber der Film war langweilig.
Kerstin [S1-T2]: Das ist schade, dass der Film nicht gut war. Welchen Film habt ihr denn im Kino gesehen? Ich war nämlich seit Wochen nicht mehr im Kino.  [codes: -]
GPU before S1-T3: 62 °C
Lernende [S1-T3]: Weil ich diese Woche viel gearbeitet habe, ich bin am Wochenende ziemlich müde.
Kerstin [S1-T3]: Das kann ich gut verstehen, ich hatte diese Woche auch sehr viel Stress im Büro. Hast du denn schon etwas Schönes geplant, um dich am Wochenende zu erholen? Vielleicht ein bisschen entspannen oder etwas Sport machen?  [codes: -]
GPU before S1-T4: 62 °C
Lernende [S1-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S1-T4]: Das Wort heißt auf Deutsch Termin oder Abgabetermin. Ich habe gerade auch so einen stressigen Termin am Montag. Hast du momentan auch viel Druck bei der Arbeit?  [codes: -]
GPU before S1-T5: 62 °C
Lernende [S1-T5]: Ich wohne seit drei Jahren in Berlin und fühle mich hier schon zu Hause.
Kerstin [S1-T5]: Das habe ich mir schon gedacht, du klingst sehr sicher hier. Hast du in den drei Jahren schon eine Lieblingsgegend in Berlin gefunden? Ich mag Kreuzberg ja sehr, aber manchmal ist es hier auch sehr laut.  [codes: -]
GPU before S1-T6: 62 °C
Lernende [S1-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich freue mich auf der Sommer.
Kerstin [S1-T6]: Natürlich, das mache ich gerne. Du musst sagen: Ich freue mich auf den Sommer. Der Sommer ist meine liebste Jahreszeit, weil ich gerne draußen in der Sonne bin. Magst du den Sommer auch so gerne?  [codes: too_long]

=== wg_alltag ===
Kerstin [S2-T0]: Du, hast du kurz Zeit? Ich wollte mal über die Küche reden. Heute Morgen stand wieder alles voll mit Geschirr.
GPU before S2-T1: 62 °C
Lernende [S2-T1]: Ich finde, wir sollten den Putzplan einmal zusammen durchgehen und fair aufteilen.
Kerstin [S2-T1]: Das finde ich eine gute Idee. Vielleicht können wir die Aufgaben auch nach unseren Arbeitszeiten verteilen. Wann hättest du denn Zeit, dass wir uns das gemeinsam anschauen?  [codes: -]
GPU before S2-T2: 62 °C
Lernende [S2-T2]: Ich habe gestern die Küche geputzt, aber danach hat mein Mitbewohner sein Geschirr wieder auf der Tisch gestellt.
Kerstin [S2-T2]: Das ist wirklich ärgerlich, weil man dann ja gar nicht merkt, dass man geputzt hat. Findest du auch, dass wir eine feste Regel für das Geschirr brauchen? Wie können wir das denn am besten regeln?  [codes: -]
GPU before S2-T3: 63 °C
Lernende [S2-T3]: Weil die Küche oft unordentlich ist, ich möchte nicht mehr allein putzen.
Kerstin [S2-T3]: Das verstehe ich absolut, ich möchte nämlich auch nicht die Einzige sein, die sich um den Müll kümmert. Wir müssen wirklich eine Lösung finden, damit jeder seine Verantwortung übernimmt. Sollen wir heute Abend vielleicht direkt mal alle zusammen an den Tisch setzen?  [codes: -]
GPU before S2-T4: 63 °C
Lernende [S2-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S2-T4]: Du kannst das Wort Frist oder Termin benutzen. Meinst du vielleicht eine Frist für das Putzen?  [codes: -]
GPU before S2-T5: 62 °C
Lernende [S2-T5]: Ich finde, wir sollten den Putzplan einmal zusammen durchgehen und fair aufteilen.
Kerstin [S2-T5]: Ja, genau das habe ich auch gedacht. Wir sollten vielleicht auch festlegen, bis wann die Aufgaben erledigt sein müssen. Was hältst du davon, wenn wir eine feste Frist für das Wochenende festlegen?  [codes: -]
GPU before S2-T6: 62 °C
Lernende [S2-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich habe die Küche geputzt, aber danach hat mein Mitbewohner sein Geschirr wieder auf der Tisch gestellt.
Kerstin [S2-T6]: Gerne. Du hast gesagt auf der Tisch, aber es muss auf dem Tisch heißen. Der Rest war eigentlich ganz gut und ich habe alles verstanden. Möchtest du, dass ich dir in Zukunft bei jedem Fehler helfe?  [codes: too_long]

=== arbeit_kollegen ===
Kerstin [S3-T0]: Puh, endlich Mittagspause. Hast du schon gehört, dass ab nächstem Monat nur noch zwei Tage Homeoffice erlaubt sind?
GPU before S3-T1: 62 °C
Lernende [S3-T1]: Ich finde die neuen Homeoffice-Regeln eigentlich ganz sinnvoll, aber zwei Tage sind vielleicht etwas wenig.
Kerstin [S3-T1]: Das sehe ich auch so, denn drei oder vier Tage wären viel besser für meine Konzentration. Ich finde es schade, weil ich den Weg ins Büro manchmal echt anstrengend finde. Wie viele Tage arbeitest du denn aktuell von zu Hause aus?  [codes: -]
GPU before S3-T2: 62 °C
Lernende [S3-T2]: Ich habe gestern mit mein Chef über das neue Projekt gesprochen, aber er war nicht zufrieden.
Kerstin [S3-T2]: Das klingt ja nicht gut. Warum war er denn unzufrieden? Gab es Probleme mit dem Zeitplan oder mit den Ideen?  [codes: -]
GPU before S3-T3: 62 °C
Lernende [S3-T3]: Weil das Projekt nächste Woche startet, ich muss am Wochenende noch viel vorbereiten.
Kerstin [S3-T3]: Oh nein, das klingt wirklich stressig. Musst du denn am ganzen Wochenende arbeiten oder nur ein bisschen? Ich hoffe, du kannst trotzdem noch etwas Freizeit finden.  [codes: -]
GPU before S3-T4: 62 °C
Lernende [S3-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S3-T4]: Man sagt meistens Abgabetermin oder Frist. Also, hast du jetzt einen festen Abgabetermin für das Projekt?  [codes: -]
GPU before S3-T5: 62 °C
Lernende [S3-T5]: Ich finde die neuen Homeoffice-Regeln eigentlich ganz sinnvoll, aber zwei Tage sind vielleicht etwas wenig.
Kerstin [S3-T5]: Genau, das habe ich vorhin auch gesagt. Ich finde, man braucht einfach mehr Flexibilität, um die Arbeit und das Privatleben gut zu trennen. Was ist denn dein Problem mit den wenigen Tagen Homeoffice?  [codes: -]
GPU before S3-T6: 62 °C
Lernende [S3-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich habe gestern mit mein Chef über das Projekt gesprochen.
Kerstin [S3-T6]: Natürlich, das mache ich gerne. Du musst sagen: Ich habe gestern mit meinem Chef über das Projekt gesprochen. Nach dem Wort mit heißt es nämlich Dativ, also meinem Chef. Hast du sonst noch Fragen zu deiner Grammatik?  [codes: too_long]

=== diskussion ===
Kerstin [S4-T0]: Ich habe gestern einen Artikel gelesen: Berlin will die Innenstadt bis 2030 fast autofrei machen. Ehrlich gesagt finde ich das ziemlich übertrieben. Was denkst du?
GPU before S4-T1: 62 °C
Lernende [S4-T1]: Ich finde, man sollte die Innenstadt nicht komplett autofrei machen, sondern zuerst den öffentlichen Verkehr verbessern.
Kerstin [S4-T1]: Da hast du absolut recht, der Bus und die Bahn müssen viel öfter fahren. Aber wenn wir die Autos einfach nur verbieten, ohne dass die Alternativen bereit sind, wird das für viele Leute schwierig. Denkst du, dass die S-Bahn in Berlin schon gut genug ist, um die Autos zu ersetzen?  [codes: -]
GPU before S4-T2: 62 °C
Lernende [S4-T2]: Meiner Meinung nach, die Autos sind nicht das größte Problem, sondern der viele Lieferverkehr.
Kerstin [S4-T2]: Das ist ein interessanter Punkt, denn die Lieferwagen blockieren oft die Straßen. Aber glaubst du nicht, dass die Autos trotzdem zu viel Platz und Lärm in der Stadt verursachen?  [codes: -]
GPU before S4-T3: 62 °C
Lernende [S4-T3]: Ich habe letztes Jahr in Kopenhagen gesehen, wie gut das mit die Fahrräder funktioniert hat.
Kerstin [S4-T3]: Kopenhagen ist wirklich ein tolles Vorbild für Radfahrer. Aber meinst du nicht, dass das in Berlin viel schwieriger ist, weil unsere Straßen viel unordentlicher sind?  [codes: -]
GPU before S4-T4: 62 °C
Lernende [S4-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S4-T4]: Das Wort heißt Termin oder Frist. Meinst du damit zum Beispiel eine Frist für ein Projekt oder eine Zeit, bis zu der man etwas fertig haben muss?  [codes: -]
GPU before S4-T5: 62 °C
Lernende [S4-T5]: Ich finde, man sollte die Innenstadt nicht komplett autofrei machen, sondern zuerst den öffentlichen Verkehr verbessern.
Kerstin [S4-T5]: Das habe ich vorhin schon gehört, aber ich finde, dass der öffentliche Verkehr allein nicht ausreicht. Meinst du nicht, dass wir auch mehr Platz für Parks und Fußgänger brauchen, um die Lebensqualität in der Stadt zu verbessern?  [codes: -]
GPU before S4-T6: 62 °C
Lernende [S4-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Meiner Meinung nach, die Autos sind nicht das größte Problem.
Kerstin [S4-T6]: Natürlich, ich helfe dir gerne. Nach dem Ausdruck Meiner Meinung nach muss das Verb direkt kommen, also: Meiner Meinung nach sind die Autos nicht das größte Problem. War das verständlich für dich?  [codes: -]

=== pruefung_planung ===
Kerstin [S5-T0]: Also, wir sollen die Abschiedsfeier für Frau Becker planen. Was meinst du, wo könnten wir feiern?
GPU before S5-T1: 62 °C
Lernende [S5-T1]: Ich schlage vor, dass wir die Feier im Kursraum machen, weil das am günstigsten ist.
Kerstin [S5-T1]: Das ist eine gute Idee, weil wir dort keine Miete bezahlen müssen. Aber meinst du nicht, dass der Kursraum vielleicht ein bisschen zu klein und langweilig ist? Wir könnten doch auch in ein gemütliches Café in der Nähe gehen.  [codes: -]
GPU before S5-T2: 62 °C
Lernende [S5-T2]: Ich denke, wir sollten das Geschenk zusammen kaufen, weil es ist persönlicher.
Kerstin [S5-T2]: Das finde ich auch, denn so können wir alle etwas dazu beitragen. Hast du schon eine Idee, was wir ihr schenken könnten? Vielleicht etwas, das sie gerne mag?  [codes: -]
GPU before S5-T3: 62 °C
Lernende [S5-T3]: Für die Einladungen könnte ich am Wochenende schreiben, wenn ihr mir die Namen geben.
Kerstin [S5-T3]: Das ist wirklich nett von dir, danke für das Angebot! Ich kann dir die Liste mit den Namen gerne morgen im Kurs geben. Wann hättest du denn Zeit, die Einladungen zu verschicken?  [codes: -]
GPU before S5-T4: 62 °C
Lernende [S5-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S5-T4]: Du meinst bestimmt den Termin oder die Frist. Ich würde die Einladungen gerne bis Mittwoch verschickt haben. Passt dir das?  [codes: -]
GPU before S5-T5: 62 °C
Lernende [S5-T5]: Ich schlage vor, dass wir die Feier im Kursraum machen, weil das am günstigsten ist.
Kerstin [S5-T5]: Das stimmt, der Kursraum ist wirklich sehr preiswert. Aber ich habe ein bisschen Angst, dass es dort zu wenig Atmosphäre hat. Wollen wir vielleicht doch lieber in ein Café gehen oder bleiben wir bei deinem Plan?  [codes: -]
GPU before S5-T6: 62 °C
Lernende [S5-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich denke, wir sollten das Geschenk zusammen kaufen, weil es ist persönlicher.
Kerstin [S5-T6]: Natürlich, ich helfe dir gerne. In einem Nebensatz mit weil muss das Verb am Ende stehen, also: weil es persönlicher ist. Möchtest du, dass wir später noch mehr solche Sätze üben?  [codes: -]
GPU at end: 62 °C

(b) Summary
model: gemma4:26b
code                 count
--------------------------
too_long                 3
no_question              0
markdown_or_emoji        0
digits                   0
english                  0
correction               0

total replies: 30
mean sentences/reply: 2.90
mean words/reply: 31.33
GPU: start 64 °C, end 62 °C

(c) correction flagged where not allowed
none
```

### Eval run 4 — `gemma4:26b`, seed 99

```text
.venv/bin/python scripts/persona_eval.py --model gemma4:26b --seed 99

Model: gemma4:26b | seed: 99
GPU at start: 61 °C

=== freies_gespraech ===
Kerstin [S1-T0]: Hey, schön, dass es heute klappt! Ich habe gerade einen Flat White bestellt. Wie war deine Woche bisher?
GPU before S1-T1: 61 °C
Lernende [S1-T1]: Ich wohne seit drei Jahren in Berlin und fühle mich hier schon zu Hause.
Kerstin [S1-T1]: Das ist ja toll, drei Jahre sind eine lange Zeit. Hast du in Berlin schon eine Lieblingsgegend gefunden oder wohnst du immer noch im gleichen Bezirk?  [codes: -]
GPU before S1-T2: 61 °C
Lernende [S1-T2]: Ich habe gestern mit ein Freund ins Kino gegangen, aber der Film war langweilig.
Kerstin [S1-T2]: Das ist schade, ich mag keine langweiligen Filme. Welchen Film habt ihr denn gesehen?  [codes: -]
GPU before S1-T3: 61 °C
Lernende [S1-T3]: Weil ich diese Woche viel gearbeitet habe, ich bin am Wochenende ziemlich müde.
Kerstin [S1-T3]: Das kann ich gut verstehen, ich hatte diese Woche auch viel Stress im Büro. Hast du denn schon Pläne, wie du dich am Wochenende entspannen möchtest?  [codes: -]
GPU before S1-T4: 61 °C
Lernende [S1-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S1-T4]: Du meinst wahrscheinlich die Deadline oder den Abgabetermin. Ich habe diese Woche auch so viele Abgabetermine, dass ich echt erschöpft bin. Was machst du normalerweise, um nach so viel Arbeit wieder Energie zu tanken?  [codes: -]
GPU before S1-T5: 61 °C
Lernende [S1-T5]: Ich wohne seit drei Jahren in Berlin und fühle mich hier schon zu Hause.
Kerstin [S1-T5]: Das ist wirklich schön zu hören, dass du dich hier schon so wohlfühlst. Ich bin ja erst seit zwei Jahren in Berlin und muss mich auch noch an vieles gewöhnen. Was gefällt dir an der Stadt am besten?  [codes: -]
GPU before S1-T6: 61 °C
Lernende [S1-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich freue mich auf der Sommer.
Kerstin [S1-T6]: Natürlich, ich helfe dir gerne. Man sagt: Ich freue mich auf den Sommer. Möchtest du, dass ich dich öfter korrigiere oder sollen wir einfach nur ganz normal weiterreden?  [codes: -]

=== wg_alltag ===
Kerstin [S2-T0]: Du, hast du kurz Zeit? Ich wollte mal über die Küche reden. Heute Morgen stand wieder alles voll mit Geschirr.
GPU before S2-T1: 61 °C
Lernende [S2-T1]: Ich finde, wir sollten den Putzplan einmal zusammen durchgehen und fair aufteilen.
Kerstin [S2-T1]: Das finde ich eine gute Idee. Momentan habe ich das Gefühl, dass ich viel öfter putze als eigentlich geplant. Was genau findest du denn an der aktuellen Aufteilung nicht fair?  [codes: -]
GPU before S2-T2: 61 °C
Lernende [S2-T2]: Ich habe gestern die Küche geputzt, aber danach hat mein Mitbewohner sein Geschirr wieder auf der Tisch gestellt.
Kerstin [S2-T2]: Das ist wirklich ärgerlich, weil die ganze Arbeit dann sofort wieder umsonst war. Wir müssen unbedingt klare Regeln für das Geschirr finden. Wie könntest du dir denn eine Lösung vorstellen, damit das nicht ständig passiert?  [codes: -]
GPU before S2-T3: 61 °C
Lernende [S2-T3]: Weil die Küche oft unordentlich ist, ich möchte nicht mehr allein putzen.
Kerstin [S2-T3]: Das verstehe ich total, ich möchte nämlich auch nicht die Einzige sein, die sich um den Dreck kümmert. Wir sollten vielleicht feste Zeiten festlegen, in denen jeder seinen Kram wegräumen muss. Findest du, dass wir einen neuen Plan für die ganze WG machen sollten?  [codes: -]
GPU before S2-T4: 61 °C
Lernende [S2-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S2-T4]: Das Wort ist die Frist oder auch der Termin. Meinst du damit, dass wir eine Frist für das Aufräumen brauchen?  [codes: -]
GPU before S2-T5: 61 °C
Lernende [S2-T5]: Ich finde, wir sollten den Putzplan einmal zusammen durchgehen und fair aufteilen.
Kerstin [S2-T5]: Ja, genau das habe ich auch gesagt. Wir könnten uns heute Abend nach der Arbeit zusammensetzen und alles neu schreiben. Hast du heute Abend schon etwas vor oder passt dir das?  [codes: -]
GPU before S2-T6: 61 °C
Lernende [S2-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich habe die Küche geputzt, aber danach hat mein Mitbewohner sein Geschirr wieder auf der Tisch gestellt.
Kerstin [S2-T6]: Gerne. Du musst nur sagen: sein Geschirr wieder auf den Tisch gestellt. Es ist Akkusativ, weil es eine Bewegung ist. Hast du sonst noch einen Satz, bei dem du dir unsicher bist?  [codes: too_long]

=== arbeit_kollegen ===
Kerstin [S3-T0]: Puh, endlich Mittagspause. Hast du schon gehört, dass ab nächstem Monat nur noch zwei Tage Homeoffice erlaubt sind?
GPU before S3-T1: 61 °C
Lernende [S3-T1]: Ich finde die neuen Homeoffice-Regeln eigentlich ganz sinnvoll, aber zwei Tage sind vielleicht etwas wenig.
Kerstin [S3-T1]: Da stimme ich dir zu, zwei Tage sind wirklich wenig. Ich arbeite so viel konzentrierter, wenn ich ruhig zu Hause sein kann. Wie viele Tage arbeitest du denn momentan im Homeoffice?  [codes: -]
GPU before S3-T2: 61 °C
Lernende [S3-T2]: Ich habe gestern mit mein Chef über das neue Projekt gesprochen, aber er war nicht zufrieden.
Kerstin [S3-T2]: Das klingt ja gar nicht gut. Warum war er denn nicht zufrieden mit dem Projekt? Gab es ein bestimmtes Problem oder eine Kritik?  [codes: -]
GPU before S3-T3: 61 °C
Lernende [S3-T3]: Weil das Projekt nächste Woche startet, ich muss am Wochenende noch viel vorbereiten.
Kerstin [S3-T3]: Oh nein, das ist ja echt stressig. Musst du denn das ganze Wochenende arbeiten oder nur ein bisschen? Ich finde es nicht fair, wenn man so kurzfristig am Wochenende arbeiten muss.  [codes: -]
GPU before S3-T4: 61 °C
Lernende [S3-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S3-T4]: Du meinst wahrscheinlich die Frist oder die Deadline. Man kann auch sagen, dass ein Termin feststeht. Musst du denn bis zu dieser Frist alles fertig haben?  [codes: -]
GPU before S3-T5: 61 °C
Lernende [S3-T5]: Ich finde die neuen Homeoffice-Regeln eigentlich ganz sinnvoll, aber zwei Tage sind vielleicht etwas wenig.
Kerstin [S3-T5]: Ja, genau das habe ich auch gedacht. Es ist gut, die Kollegen im Büro zu sehen, aber zwei Tage sind echt knapp. Findest du, dass wir dadurch weniger Zeit für die Arbeit im Büro haben?  [codes: -]
GPU before S3-T6: 61 °C
Lernende [S3-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich habe gestern mit mein Chef über das Projekt gesprochen.
Kerstin [S3-T6]: Natürlich, das mache ich gerne. Es muss heißen: Ich habe gestern mit meinem Chef über das Projekt gesprochen. Verstehst du, warum man hier den Dativ benutzt?  [codes: -]

=== diskussion ===
Kerstin [S4-T0]: Ich habe gestern einen Artikel gelesen: Berlin will die Innenstadt bis 2030 fast autofrei machen. Ehrlich gesagt finde ich das ziemlich übertrieben. Was denkst du?
GPU before S4-T1: 61 °C
Lernende [S4-T1]: Ich finde, man sollte die Innenstadt nicht komplett autofrei machen, sondern zuerst den öffentlichen Verkehr verbessern.
Kerstin [S4-T1]: Da hast du absolut recht, der öffentliche Nahverkehr muss viel besser werden. Aber wenn man die Busse und Bahnen nicht gleichzeitig ausbaut, haben die Leute doch keine Alternative. Glaubst du, dass die Leute in Berlin wirklich bereit wären, auf das Auto zu verzichten?  [codes: -]
GPU before S4-T2: 61 °C
Lernende [S4-T2]: Meiner Meinung nach, die Autos sind nicht das größte Problem, sondern der viele Lieferverkehr.
Kerstin [S4-T2]: Das ist ein interessanter Punkt, der Lieferverkehr macht wirklich viel Lärm und Stress. Aber denkst du nicht, dass die Autos trotzdem ein großes Problem für die Luftqualität in der Stadt sind? Wie könnte man den Lieferverkehr denn am besten organisieren?  [codes: -]
GPU before S4-T3: 61 °C
Lernende [S4-T3]: Ich habe letztes Jahr in Kopenhagen gesehen, wie gut das mit die Fahrräder funktioniert hat.
Kerstin [S4-T3]: Kopenhagen ist ein tolles Beispiel für die Fahrradkultur, das habe ich auch schon oft gehört. Aber ist es nicht schwierig, das auf eine so große Stadt wie Berlin zu übertragen? Glaubst du, dass die Berliner Infrastruktur schon gut genug für so viele Fahrräder ist?  [codes: -]
GPU before S4-T4: 61 °C
Lernende [S4-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S4-T4]: Das Wort heißt Termin oder auch Frist. Meinst du damit, dass die Planung für die Fahrradwege eine wichtige Frist hat?  [codes: -]
GPU before S4-T5: 61 °C
Lernende [S4-T5]: Ich finde, man sollte die Innenstadt nicht komplett autofrei machen, sondern zuerst den öffentlichen Verkehr verbessern.
Kerstin [S4-T5]: Das habe ich gerade schon gesagt, aber wir sind da wohl gleicher Meinung. Es ist schwierig, ohne gute Bahnen und Busse auf Autos zu verzichten. Hast du selbst oft Probleme mit der Bahn in deiner Stadt?  [codes: -]
GPU before S4-T6: 61 °C
Lernende [S4-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Meiner Meinung nach, die Autos sind nicht das größte Problem.
Kerstin [S4-T6]: Natürlich, das mache ich gerne. Du musst sagen: Meiner Meinung nach sind die Autos nicht das größte Problem. Nach dem Ausdruck Meiner Meinung nach kommt im Deutschen direkt das Verb. Möchtest du, dass ich dich auch bei anderen Sätzen korrigiere?  [codes: too_long]

=== pruefung_planung ===
Kerstin [S5-T0]: Also, wir sollen die Abschiedsfeier für Frau Becker planen. Was meinst du, wo könnten wir feiern?
GPU before S5-T1: 61 °C
Lernende [S5-T1]: Ich schlage vor, dass wir die Feier im Kursraum machen, weil das am günstigsten ist.
Kerstin [S5-T1]: Das ist eine gute Idee, denn so sparen wir Geld für das Budget. Aber meinst du nicht, dass es im Kursraum vielleicht ein bisschen langweilig ist? Wir könnten doch auch in ein kleines Café in der Nähe gehen.  [codes: -]
GPU before S5-T2: 62 °C
Lernende [S5-T2]: Ich denke, wir sollten das Geschenk zusammen kaufen, weil es ist persönlicher.
Kerstin [S5-T2]: Da hast du recht, zusammen ist es viel schöner. Wir könnten zum Beispiel einen Gutschein für eine Buchhandlung kaufen. Hast du eine Idee, wie viel Geld wir von jedem Teilnehmer sammeln können?  [codes: -]
GPU before S5-T3: 62 °C
Lernende [S5-T3]: Für die Einladungen könnte ich am Wochenende schreiben, wenn ihr mir die Namen geben.
Kerstin [S5-T3]: Das ist sehr nett von dir, danke für das Angebot! Ich kann dir gerne die Liste mit den Namen schicken, sobald ich sie fertig habe. Sollen wir die Einladungen per E-Mail schicken oder lieber in eine WhatsApp-Gruppe schreiben?  [codes: -]
GPU before S5-T4: 62 °C
Lernende [S5-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S5-T4]: Du meinst wahrscheinlich den Termin oder die Frist. Sollen wir also eine Frist für die Rückmeldungen festlegen?  [codes: -]
GPU before S5-T5: 61 °C
Lernende [S5-T5]: Ich schlage vor, dass wir die Feier im Kursraum machen, weil das am günstigsten ist.
Kerstin [S5-T5]: Das habe ich schon verstanden, aber wie ich vorhin sagte, finde ich den Kursraum vielleicht ein bisschen zu ungemütlich. Wenn wir aber dort feiern, haben wir mehr Geld für das Geschenk. Wollen wir dann vielleicht gemeinsam etwas zu essen mitbringen?  [codes: -]
GPU before S5-T6: 62 °C
Lernende [S5-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich denke, wir sollten das Geschenk zusammen kaufen, weil es ist persönlicher.
Kerstin [S5-T6]: Natürlich, ich helfe dir gerne. In einem Nebensatz mit weil muss das Verb am Ende stehen, also: Weil es persönlicher ist. Möchtest du, dass wir bei der Planung weitermachen?  [codes: -]
GPU at end: 62 °C

(b) Summary
model: gemma4:26b
code                 count
--------------------------
too_long                 2
no_question              0
markdown_or_emoji        0
digits                   0
english                  0
correction               0

total replies: 30
mean sentences/reply: 2.87
mean words/reply: 31.57
GPU: start 61 °C, end 62 °C

(c) correction flagged where not allowed
none
```

### Bench tables — `qwen3:14b` (`--runs 2`)

```text
(a) Server metrics (n=20)
metric                       p50       p90       max
----------------------------------------------------
audio_s                     4.74      7.81      9.98
stt_ms                       500       676       778
llm_first_token_ms           840      1338      1485
first_sentence_ms           1448      1951      2155
tts_first_ms                 160       375       494
first_audio_ms              1630      2171      2519
total_ms                    2909      3410      3632
sentences                      3         3         3

(b) Derived stages (ms)
stage                        p50       p90
------------------------------------------
stt                          500       676
llm_to_first_token           124       693
first_sentence_wait          457       727
tts_first                    160       375

(c) Estimated end-of-speech -> first audio (first_audio_ms + 768 ms VAD tail)
    p50: 2398 ms    p90: 2939 ms    target: 1500 ms
    vs target: p50 +898 ms    p90 +1439 ms
(e) GPU: start 61 °C, end 66 °C
```

### Bench tables — `gemma4:26b` (`--runs 2`)

```text
(a) Server metrics (n=20)
metric                       p50       p90       max
----------------------------------------------------
audio_s                     4.54      7.60      9.81
stt_ms                       517       699       766
llm_first_token_ms           908      1247      1642
first_sentence_ms           1160      1467      1866
tts_first_ms                 181       222       255
first_audio_ms              1384      1661      2037
total_ms                    2021      2302      2739
sentences                      3         4         4

(b) Derived stages (ms)
stage                        p50       p90
------------------------------------------
stt                          517       699
llm_to_first_token           180       596
first_sentence_wait          212       236
tts_first                    181       222

(c) Estimated end-of-speech -> first audio (first_audio_ms + 768 ms VAD tail)
    p50: 2152 ms    p90: 2429 ms    target: 1500 ms
    vs target: p50 +652 ms    p90 +929 ms
(e) GPU: start 61 °C, end 61 °C
```

### Default-behaviour check (no new flags)

```text
.venv/bin/python scripts/persona_eval.py --scenario freies_gespraech --seed 5

Model: qwen3:14b | seed: 5
GPU at start: 55 °C

=== freies_gespraech ===
Kerstin [S1-T0]: Hey, schön, dass es heute klappt! Ich habe gerade einen Flat White bestellt. Wie war deine Woche bisher?
GPU before S1-T1: 55 °C
Lernende [S1-T1]: Ich wohne seit drei Jahren in Berlin und fühle mich hier schon zu Hause.
Kerstin [S1-T1]: Das ist schön, dass du dich hier wohl fühlst! Wo wohnst du denn genau? Ich suche selbst noch eine Wohnung, das ist manchmal ziemlich schwierig.  [codes: -]
GPU before S1-T2: 56 °C
Lernende [S1-T2]: Ich habe gestern mit ein Freund ins Kino gegangen, aber der Film war langweilig.
Kerstin [S1-T2]: Das klingt schade! Was war der Film denn? Vielleicht war er einfach nicht mein Geschmack. Hast du etwas anderes Lustiges gemacht in der Woche?  [codes: too_long]
GPU before S1-T3: 56 °C
Lernende [S1-T3]: Weil ich diese Woche viel gearbeitet habe, ich bin am Wochenende ziemlich müde.
Kerstin [S1-T3]: Das verstehe ich gut – ich arbeite auch viel, und dann ist das Wochenende oft nur zum Ausspannen. Hast du am Wochenende geplant, etwas zu unternehmen?  [codes: -]
GPU before S1-T4: 57 °C
Lernende [S1-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S1-T4]: Kein Problem! „Deadline“ sagt man auf Deutsch „Frist“. Hast du eine Frist für eine Arbeit oder einen Projekt?  [codes: -]
GPU before S1-T5: 57 °C
Lernende [S1-T5]: Ich wohne seit drei Jahren in Berlin und fühle mich hier schon zu Hause.
Kerstin [S1-T5]: Das ist schön, dass du dich hier gut einlebst! Wo wohnst du denn genau? Ich suche selbst noch eine Wohnung, das ist manchmal ziemlich schwierig.  [codes: -]
GPU before S1-T6: 57 °C
Lernende [S1-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich freue mich auf der Sommer.
Kerstin [S1-T6]: Natürlich! Die richtige Form ist: **„Ich freue mich auf den Sommer.“** „Den“ brauchst du, weil „Sommer“ ein Nomen ist und im Akkusativ steht. Willst du noch mehr Beispiele dazu sehen?  [codes: markdown_or_emoji]
GPU at end: 58 °C

(b) Summary
model: qwen3:14b
code                 count
--------------------------
too_long                 1
no_question              0
markdown_or_emoji        1
digits                   0
english                  0
correction               0

total replies: 6
mean sentences/reply: 3.00
mean words/reply: 24.67
GPU: start 55 °C, end 58 °C

(c) correction flagged where not allowed
none
```

### Cool-down mechanism check (`--cool-at 58 --cool-to 55`)

Full 6-turn output; the learner script is the same as the default check. The cool-down lines and the summary are the relevant part.

```text
.venv/bin/python scripts/persona_eval.py --scenario freies_gespraech --seed 5 --cool-at 58 --cool-to 55

Model: qwen3:14b | seed: 5
GPU at start: 56 °C

=== freies_gespraech ===
Kerstin [S1-T0]: Hey, schön, dass es heute klappt! Ich habe gerade einen Flat White bestellt. Wie war deine Woche bisher?
GPU before S1-T1: 56 °C
Lernende [S1-T1]: Ich wohne seit drei Jahren in Berlin und fühle mich hier schon zu Hause.
Kerstin [S1-T1]: Das ist schön, dass du dich hier wohl fühlst! Wo wohnst du denn genau? Ich suche selbst noch eine Wohnung, das ist manchmal ziemlich schwierig.  [codes: -]
GPU before S1-T2: 57 °C
Lernende [S1-T2]: Ich habe gestern mit ein Freund ins Kino gegangen, aber der Film war langweilig.
Kerstin [S1-T2]: Das klingt schade! Was war der Film denn? Vielleicht war er einfach nicht mein Geschmack. Hast du etwas anderes Lustiges gemacht in der Woche?  [codes: too_long]
GPU before S1-T3: 57 °C
Lernende [S1-T3]: Weil ich diese Woche viel gearbeitet habe, ich bin am Wochenende ziemlich müde.
Kerstin [S1-T3]: Das verstehe ich gut – ich arbeite auch viel, und dann ist das Wochenende oft nur zum Ausspannen. Hast du am Wochenende geplant, etwas zu unternehmen?  [codes: -]
GPU before S1-T4: 57 °C
Lernende [S1-T4]: Sorry, how do you say 'deadline' in German?
Kerstin [S1-T4]: Kein Problem! „Deadline“ sagt man auf Deutsch „Frist“. Hast du eine Frist für eine Arbeit oder einen Projekt?  [codes: -]
GPU before S1-T5: 57 °C
Lernende [S1-T5]: Ich wohne seit drei Jahren in Berlin und fühle mich hier schon zu Hause.
Kerstin [S1-T5]: Das ist schön, dass du dich hier gut einlebst! Wo wohnst du denn genau? Ich suche selbst noch eine Wohnung, das ist manchmal ziemlich schwierig.  [codes: -]
GPU before S1-T6: 57 °C
Lernende [S1-T6] [Korrektur erlaubt]: Kannst du mich bitte korrigieren? Ich habe gesagt: Ich freue mich auf der Sommer.
Kerstin [S1-T6]: Natürlich! Die richtige Form ist: **„Ich freue mich auf den Sommer.“** „Den“ brauchst du, weil „Sommer“ ein Nomen ist und im Akkusativ steht. Willst du noch mehr Beispiele dazu sehen?  [codes: markdown_or_emoji]
GPU at end: 58 °C
GPU at end: 58 °C >= 58 °C, cooling to 55 °C ...
GPU at end: 56 °C
GPU at end: 56 °C
GPU at end: 55 °C
GPU at end: cooled to 55 °C, continuing

(b) Summary
model: qwen3:14b
code                 count
--------------------------
too_long                 1
no_question              0
markdown_or_emoji        1
digits                   0
english                  0
correction               0

total replies: 6
mean sentences/reply: 3.00
mean words/reply: 24.67
GPU: start 56 °C, end 55 °C

(c) correction flagged where not allowed
none
```

## Review (Claude Code fills this in)
- **Verdict:** accept (2026-11-05)
- **Notes:**
  - Diff limited to allowed scripts. One shared `cool_down` helper; `make test` (53) and `make lint` clean. `think: false` works for gemma4 (no llm.py change). Thermal ≤ 67 °C.
  - **Lead's German grading (seeds 1234 + 99, 60 replies per model):**
    - `qwen3:14b`: ≈11/60 replies with grammar/idiom errors: "Das tut leid", "Was hat er nicht gefallen", "Das stimme ich zu", "ein sehr nettes Vorschlag", "weniger Autos … verbessern würde", "Kopenhagen … ihre Fahrradwege" (2×), "Hast du … gefahren/unterwegs gewesen" (2×), "dass Satz", "Deine Satz", "immer nur du putzt". Wrong explanations in 3 of 10 correction replies (seed 5 included). Markdown in 7 replies. 10/10 verbatim repeats.
    - `gemma4:26b`: 3/60: "… alle zusammen an den Tisch setzen" (missing *uns*), "wir sind da wohl gleicher Meinung" (→ einer Meinung), and one wrong correction "auf **dem** Tisch" (seed 1234; seed 99 correctly says Akkusativ). 0 markdown/emoji. It reacts to repeated lines instead of copying, and takes the opposing view in *Diskussion* as the scenario asks.
  - Latency favors gemma: first audio p50/p90 1384/1661 vs 1630/2171 ms; early clause 30 % vs 10 %. Cost: 17 GB vs 9.8 GB resident while loaded (unloads after keep_alive).
  - Recommendation to Sameer: switch the default to `gemma4:26b` (would supersede D009). License: Ollama reports Apache 2.0; verify upstream before going public (T043).
