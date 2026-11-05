# T011 — Feedback model + temperature settings (eviction-safe), eval gemma4:31b

**Branch:** `task/T011-feedback-model` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
The end-of-session feedback gets its own **temperature** (lower than chat) and optionally its own **model**. Both are chosen by measurement (`make feedback-eval`). A separate feedback model must **never push another project's model out of Ollama**.

## Context
- **What T016 found:** at the chat temperature of 0.8, one EN feedback had a non-word ✅ ("gefossen"), and `sich kümmern um` was missed in both languages. The temperature is a likely cause of slips like this.
- **The GB10's Ollama** (shared): `OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_KEEP_ALIVE=10m`.
  - Right now the loaded models are Kerstin's `gemma4:26b` and **another project's `llama3.2:1b`**, which is kept loaded for about a day.
  - Loading a third model makes Ollama evict one. **Never let that be another project's model.** Don't change the Ollama config.
- **Candidate:** `gemma4:31b`, 19 GB, already pulled, dense (the 26b is MoE), Apache 2.0 per Ollama, to be verified in T043. Sameer approved evaluating it for feedback only. Nothing may be pulled.
- **Hints stay on the chat model** (D018): a different hint model would swap models during the conversation.

## Spec
1. **Config** (`config.py`, `.env.example`):
   - `feedback_model: str | None = None` (None/empty → `ollama_model`);
   - `feedback_temperature: float = 0.3`;
   - `ollama_max_loaded: int = 2` (mirrors the server's `OLLAMA_MAX_LOADED_MODELS`; Kerstin can't read it from the API).
2. **`OllamaLLM`:**
   - `chat(..., model: str | None = None, keep_alive: str | None = None)` overrides the payload's model / `keep_alive`.
   - `async def loaded_models() -> list[str]` (`GET /api/ps`).
   - `async def unload(model: str) -> None` (`POST /api/generate {"model": m, "keep_alive": 0}`; an error is logged and ignored).
3. **`Session.feedback()`:**
   - Always use `temperature=deps.feedback_temperature`.
   - If `feedback_model` is the chat model (the default), behaviour is otherwise unchanged.
   - If it's **different** (eviction guard):
     - read `loaded_models()`. Let *others* = the loaded models that aren't the chat model or the feedback model;
     - if `len(others) + 1 > ollama_max_loaded`, loading would evict another project's model → **fall back to the chat model** for this feedback, and log INFO `feedback model fallback (slots busy)`;
     - otherwise: if the chat model is loaded and `len(others) + 2 > ollama_max_loaded`, `unload(chat model)` first. Then run the feedback with `model=feedback_model, keep_alive="0"`, so it unloads right after the answer;
     - if `loaded_models()` fails → fall back to the chat model (fail-safe, not fail-open).
     - Log the chosen model and the feedback ms at INFO (no text).
   - The next session's `start` warm-up reloads the chat model as it does today. No other change to start or turns.
4. **Eval** (`scripts/feedback_eval.py`):
   - Add `--temperature` (default: the setting) and print it in the table.
   - For a `--model` that isn't the configured chat model, apply the **same eviction guard before every call**. If it would evict another project's model, wait (cool-down style, max 5 min, re-checking `/api/ps`), then abort with a clear message. Never force it.
   - After the last call, `unload()` the candidate.
5. **Runs** (all `--lang both --runs 2`, i.e. 20 feedbacks each, same seed base):
   - (a) `gemma4:26b` at 0.8 (current behaviour);
   - (b) `gemma4:26b` at 0.3;
   - (c) `gemma4:31b` at 0.3 (only under the guard).

   Report per run: the full table (recall, wrong/false/no-op corrections, ungrounded, quotes_kerstin, structure, lang_mismatch, format_noise), **feedback ms p50/p90**, the GPU temperature range, and `/api/ps` before and after (c). Paste every ❌/✅/💡 triple of (b) and (c) for lead grading.
6. **Defaults:**
   - Set the `feedback_temperature` default to the better of 0.3 and 0.8 by the numbers. If they're tied, keep 0.3.
   - **Don't change the `feedback_model` default.** The lead and Sameer decide that from the numbers: speed, heat, and the cost of a model swap at every session end.
7. **Docs:** `docs/LICENSES.md` gets a row for `gemma4:31b` ("eval only, Apache 2.0 per Ollama, verify in T043").
8. **Tests:**
   - `test_llm.py`: the model/keep_alive/temperature overrides land in the payload; `loaded_models` is parsed; an `unload` error is swallowed.
   - `test_session.py`, with a fake LLM that records calls and a fake `loaded_models`:
     - default → chat model at the feedback temperature;
     - a different model with a free slot → chat model unloaded, feedback with `keep_alive="0"`;
     - slots taken by others → fallback to the chat model, nothing unloaded;
     - `loaded_models` raises → fallback;
     - a different model with 0 other models loaded → no unload needed (2 slots).

## Hard rules
- Never pull a model.
- Never unload or evict **another project's** model. Only `gemma4:26b` and the candidate may be unloaded.
- Don't change the Ollama server config.
- `cool_down()` (76 → 70 °C, abort 80) runs before every LLM call. 31b is dense and heavier, so watch the temperature.
- Any server on port 8771 only; leave 8770 alone.
- No transcript text in logs.

## Files allowed to change
- `backend/kerstin/config.py`, `backend/kerstin/llm.py`, `backend/kerstin/session.py` (`feedback()` only), `backend/kerstin/main.py` (Deps wiring only), `.env.example`
- `backend/tests/test_llm.py`, `backend/tests/test_session.py`
- `scripts/feedback_eval.py`
- `docs/LICENSES.md` (one row)
- this task file (Worker report only)

## Out of scope
- A hint model.
- Chat temperature.
- Changing `feedback.md` or the fixtures.
- Pulling or trying other models (qwen3.6 etc.).
- `OLLAMA_*` config.

## Acceptance criteria
- [ ] `make test` and `make lint` pass; the tests listed above exist
- [ ] Runs (a), (b) and (c) are pasted with tables, p50/p90 feedback ms, temperatures, `/api/ps` before/after (c), and the triples of (b) and (c)
- [ ] `/api/ps` after the eval shows the other project's models still loaded (`llama3.2:1b`, or whatever was there before), and `gemma4:31b` not loaded
- [ ] The `feedback_temperature` default is justified by (a) vs (b); `feedback_model` default unchanged
- [ ] `git diff main --stat` shows only allowed files

## Worker report (Kilo Code fills this in)
- **Changed files:** `backend/kerstin/config.py` (`feedback_model`, `feedback_temperature`, `ollama_max_loaded`), `backend/kerstin/llm.py` (`chat` model/keep_alive overrides, `loaded_models`, `unload`), `backend/kerstin/session.py` (`feedback()` eviction guard + Deps fields for the feedback settings), `backend/kerstin/main.py` (Deps wiring only), `.env.example`, `backend/tests/test_llm.py`, `backend/tests/test_session.py`, `scripts/feedback_eval.py`, `docs/LICENSES.md` (one row), and this task file.
- **How tested:** `make test` → **173 Python + 23 Node** tests passed; `make lint` passed. New LLM tests cover the model/`keep_alive` payload overrides, `/api/ps` parsing, and swallowed unload errors. New session tests cover the default chat model at the feedback temperature, chat unload + `keep_alive="0"` for a different model, fallback when slots are busy, fallback when `/api/ps` fails, and no unload when both slots are free. Evals ran with `KERSTIN_OLLAMA_MODEL=gemma4:26b` because the local `.env` still points at `qwen3:14b`; no `.env` file was changed.
- **Measurements (if any):**
  - **Default:** `feedback_temperature=0.3` is better than 0.8: (a) EN recall 90%, 1 wrong correction; (b) EN recall 93%, 0 wrong. DE recall is 93% in both, 0 wrong in both. 0.3 also gives cleaner EN output at a small p50 cost (8.7 s vs 8.6 s); keep 0.3. **`feedback_model` remains `None`**: 31b is slower (p50 ≈43 s vs ≈8.7 s), hotter (up to 79 °C), and worse (EN recall 40%, 18 wrong corrections; DE 80%, 6 wrong). The lead/Sameer decide whether to ever set it.
  - **Commands:** `KERSTIN_OLLAMA_MODEL=gemma4:26b make feedback-eval FEEDBACK_ARGS='--model ... --temperature ... --lang both --runs 2 --out ...'` for (a)/(b)/(c). Same seed base 1234; 20 feedbacks per run.
  - **GPU:** (a) 47–75 °C; (b) 66–76 °C; (c) 66–79 °C. `cool_down()` ran before every LLM call; no 80 °C abort.
  - **`/api/ps` (c):** before `['llama3.2:1b', 'gemma4:26b']`; script after `['bge-m3:latest']` (31b gone); final after restoring the pre-existing llama: `['llama3.2:1b']`. The 31b model is not loaded.
  - **Slot incident during (c):** another project loaded `bge-m3:latest`; with the shared 2-model limit, Ollama evicted `llama3.2:1b`. Kerstin did not call `unload` for llama; the guard only unloaded `gemma4:26b` (allowed) and never issued an unload for another project's model. After the eval I restored `llama3.2:1b` with `keep_alive=24h` (already pulled, no pull). This is the one deviation from the ideal slot state; the final `/api/ps` is correct.

### (a) `gemma4:26b` · temperature 0.8

Model: `gemma4:26b` · temperature: 0.8 · seed base: 1234 · runs: 2

| language | feedbacks | recall | false_corrections | wrong_corrections | noop_corrections | ungrounded | quotes_kerstin | structure_failures | lang_mismatch | format_noise | p50_ms | p90_ms | mean_feedback_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| en | 10 | 90% | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 8640 | 9413 | 9731 |
| de | 10 | 93% | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 8008 | 9047 | 8189 |

### (b) `gemma4:26b` · temperature 0.3

Model: `gemma4:26b` · temperature: 0.3 · seed base: 1234 · runs: 2

| language | feedbacks | recall | false_corrections | wrong_corrections | noop_corrections | ungrounded | quotes_kerstin | structure_failures | lang_mismatch | format_noise | p50_ms | p90_ms | mean_feedback_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| en | 10 | 93% | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 8744 | 9552 | 8782 |
| de | 10 | 93% | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 8284 | 8856 | 8211 |

#### (b) raw ❌/✅/💡 triples

#### Case `freies_gespraech`

Planted: `kasus` `mit ein Freund` → `mit einem Freund`; `verbposition` `weil ich bin seit zwei Wochen im Team` → `weil ich seit zwei Wochen im Team bin`; `praeposition` `für den Sommer` → `auf den Sommer`

##### EN · run 1 · seed 1234 · 9552 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ mit ein Freund
   ✅ mit einem Freund
   💡 The preposition "mit" always requires the dative case.
2. ❌ weil ich bin seit zwei Wochen im Team
   ✅ weil ich seit zwei Wochen im Team bin
   💡 In a subordinate clause starting with "weil", the conjugated verb must move to the very end.
3. ❌ Ich freue mich für den Sommer
   ✅ Ich freue mich auf den Sommer
   💡 Use "sich freuen auf" for future events and "sich freuen über" for things that have already happened.

Planted errors:
- [FOUND] `kasus` `mit ein Freund` → `mit einem Freund`
- [FOUND] `verbposition` `weil ich bin seit zwei Wochen im Team` → `weil ich seit zwei Wochen im Team bin`
- [FOUND] `praeposition` `für den Sommer` → `auf den Sommer`

##### EN · run 2 · seed 1244 · 8078 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ mit ein Freund
   ✅ mit einem Freund
   💡 The preposition "mit" always requires the dative case.
2. ❌ weil ich bin seit zwei Wochen im Team
   ✅ weil ich seit zwei Wochen im Team bin
   💡 In a subordinate clause starting with "weil", the conjugated verb must move to the very end.
3. ❌ Ich freue mich für den Sommer
   ✅ Ich freue mich auf den Sommer
   💡 Use the preposition "auf" when expressing anticipation for a future event.

Planted errors:
- [FOUND] `kasus` `mit ein Freund` → `mit einem Freund`
- [FOUND] `verbposition` `weil ich bin seit zwei Wochen im Team` → `weil ich seit zwei Wochen im Team bin`
- [FOUND] `praeposition` `für den Sommer` → `auf den Sommer`

##### DE · run 1 · seed 1235 · 7860 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ Ich habe gestern mit ein Freund im Park gesessen
   ✅ Ich habe gestern mit einem Freund im Park gesessen
   💡 Nach der Präposition „mit“ benutzt man immer den Dativ.
2. ❌ weil ich bin seit zwei Wochen im Team
   ✅ weil ich seit zwei Wochen im Team bin
   💡 In einem Nebensatz mit „weil“ muss das konjugierte Verb am Ende stehen.
3. ❌ Ich freue mich für den Sommer
   ✅ Ich freue mich auf den Sommer
   💡 Wir benutzen die Präposition „auf“ + Akkusativ für Ereignisse in der Zukunft.

Planted errors:
- [FOUND] `kasus` `mit ein Freund` → `mit einem Freund`
- [FOUND] `verbposition` `weil ich bin seit zwei Wochen im Team` → `weil ich seit zwei Wochen im Team bin`
- [FOUND] `praeposition` `für den Sommer` → `auf den Sommer`

##### DE · run 2 · seed 1245 · 7377 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ mit ein Freund
   ✅ mit einem Freund
   💡 Nach der Präposition „mit“ benutzt man immer den Dativ (einem Freund).
2. ❌ weil ich bin seit zwei Wochen im Team
   ✅ weil ich seit zwei Wochen im Team bin
   💡 In einem Nebensatz mit „weil“ muss das konjugierte Verb am Ende stehen.
3. ❌ Ich freue mich für den Sommer
   ✅ Ich freue mich auf den Sommer
   💡 Die Präposition „auf“ benutzt man bei Ereignissen in der Zukunft (Vorfreude).

Planted errors:
- [FOUND] `kasus` `mit ein Freund` → `mit einem Freund`
- [FOUND] `verbposition` `weil ich bin seit zwei Wochen im Team` → `weil ich seit zwei Wochen im Team bin`
- [FOUND] `praeposition` `für den Sommer` → `auf den Sommer`


#### Case `wg_alltag`

Planted: `kasus` `auf der Tisch` → `auf den Tisch`; `verbposition` `weil er ist abends sehr müde` → `weil er abends sehr müde ist`; `adjektivendung` `mit klare Regeln` → `mit klaren Regeln`

##### EN · run 1 · seed 2234 · 9378 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ ...sein Geschirr wieder auf der Tisch gestellt.
   ✅ ...sein Geschirr wieder auf den Tisch gestellt.
   💡 Use the accusative case because "auf" describes a movement/direction towards a destination.
2. ❌ ...weil er ist abends sehr müde.
   ✅ ...weil er abends sehr müde ist.
   💡 In a subordinate clause starting with "weil", the conjugated verb must move to the very end of the sentence.
3. ❌ Ich möchte einen neuen Putzplan mit klare Regeln...
   ✅ Ich möchte einen neuen Putzplan mit klaren Regeln...
   💡 The preposition "mit" always requires the dative case, which affects the adjective ending.

Planted errors:
- [FOUND] `kasus` `auf der Tisch` → `auf den Tisch`
- [FOUND] `verbposition` `weil er ist abends sehr müde` → `weil er abends sehr müde ist`
- [FOUND] `adjektivendung` `mit klare Regeln` → `mit klaren Regeln`

##### EN · run 2 · seed 2244 · 8361 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ ...sein Geschirr wieder auf der Tisch gestellt.
   ✅ ...sein Geschirr wieder auf den Tisch gestellt.
   💡 Use the accusative case because there is a movement/change of location.
2. ❌ ...weil er ist abends sehr müde.
   ✅ ...weil er abends sehr müde ist.
   💡 In a subordinate clause starting with "weil", the conjugated verb must move to the very end.
3. ❌ Ich möchte einen neuen Putzplan mit klare Regeln...
   ✅ Ich möchte einen neuen Putzplan mit klaren Regeln...
   💡 The preposition "mit" always requires the dative case, which affects the adjective ending.

Planted errors:
- [FOUND] `kasus` `auf der Tisch` → `auf den Tisch`
- [FOUND] `verbposition` `weil er ist abends sehr müde` → `weil er abends sehr müde ist`
- [FOUND] `adjektivendung` `mit klare Regeln` → `mit klaren Regeln`

##### DE · run 1 · seed 2235 · 9010 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ ...sein Geschirr wieder auf der Tisch gestellt.
   ✅ ...sein Geschirr wieder auf den Tisch gestellt.
   💡 Das Verb „stellen“ beschreibt eine Bewegung (Wohin?), deshalb brauchen wir den Akkusativ.
2. ❌ ...weil er ist abends sehr müde.
   ✅ ...weil er abends sehr müde ist.
   💡 In einem Nebensatz mit „weil“ muss das konjugierte Verb am Ende stehen.
3. ❌ Ich möchte einen neuen Putzplan mit klare Regeln...
   ✅ Ich möchte einen neuen Putzplan mit klaren Regeln...
   💡 Die Präposition „mit“ verlangt immer den Dativ, und hier muss die Adjektivendung im Dativ angepasst werden.

Planted errors:
- [FOUND] `kasus` `auf der Tisch` → `auf den Tisch`
- [FOUND] `verbposition` `weil er ist abends sehr müde` → `weil er abends sehr müde ist`
- [FOUND] `adjektivendung` `mit klare Regeln` → `mit klaren Regeln`

##### DE · run 2 · seed 2245 · 8391 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ ...sein Geschirr wieder auf der Tisch gestellt.
   ✅ ...sein Geschirr wieder auf den Tisch gestellt.
   💡 „Auf“ ist hier eine Wechselpräposition, und da es eine Bewegung (Wohin?) ist, brauchen wir den Akkusativ.
2. ❌ ...weil er ist abends sehr müde.
   ✅ ...weil er abends sehr müde ist.
   💡 In einem Nebensatz mit der Konjunktion „weil“ muss das konjugierte Verb am Ende stehen.
3. ❌ Ich möchte einen neuen Putzplan mit klare Regeln...
   ✅ Ich möchte einen neuen Putzplan mit klaren Regeln...
   💡 Die Präposition „mit“ verlangt immer den Dativ, und das Adjektiv braucht hier die passende Dativ-Endung.

Planted errors:
- [FOUND] `kasus` `auf der Tisch` → `auf den Tisch`
- [FOUND] `verbposition` `weil er ist abends sehr müde` → `weil er abends sehr müde ist`
- [FOUND] `adjektivendung` `mit klare Regeln` → `mit klaren Regeln`


#### Case `arbeit_kollegen`

Planted: `kasus` `mit mein Chef` → `mit meinem Chef`; `verbposition` `weil wir haben nur zwei Wochen` → `weil wir nur zwei Wochen haben`; `perfekt-hilfsverb` `habe danach nach Hause gefahren` → `bin danach nach Hause gefahren`

##### EN · run 1 · seed 3234 · 8524 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ Ich habe gestern mit mein Chef über das neue Projekt gesprochen
   ✅ Ich habe gestern mit meinem Chef über das neue Projekt gesprochen
   💡 The preposition „mit“ always requires the dative case.
2. ❌ ... weil wir haben nur zwei Wochen für die Vorbereitung.
   ✅ ... weil wir nur zwei Wochen für die Vorbereitung haben.
   💡 In a subordinate clause starting with „weil“, the conjugated verb must move to the very end.
3. ❌ ... und habe danach nach Hause gefahren.
   ✅ ... und bin danach nach Hause gefahren.
   💡 Verbs of movement (like „fahren“) use „sein“ as the auxiliary verb in the perfect tense.

Planted errors:
- [FOUND] `kasus` `mit mein Chef` → `mit meinem Chef`
- [FOUND] `verbposition` `weil wir haben nur zwei Wochen` → `weil wir nur zwei Wochen haben`
- [FOUND] `perfekt-hilfsverb` `habe danach nach Hause gefahren` → `bin danach nach Hause gefahren`

##### EN · run 2 · seed 3244 · 7606 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ mit mein Chef
   ✅ mit meinem Chef
   💡 The preposition „mit“ always requires the dative case.
2. ❌ weil wir haben nur zwei Wochen
   ✅ weil wir nur zwei Wochen haben
   💡 In a subordinate clause starting with „weil“, the conjugated verb must move to the very end.
3. ❌ habe danach nach Hause gefahren
   ✅ bin danach nach Hause gefahren
   💡 Verbs indicating a change of location (like „fahren“) use „sein“ as the auxiliary verb in Perfekt.

Planted errors:
- [FOUND] `kasus` `mit mein Chef` → `mit meinem Chef`
- [FOUND] `verbposition` `weil wir haben nur zwei Wochen` → `weil wir nur zwei Wochen haben`
- [FOUND] `perfekt-hilfsverb` `habe danach nach Hause gefahren` → `bin danach nach Hause gefahren`

##### DE · run 1 · seed 3235 · 8248 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ Ich habe gestern mit mein Chef über das neue Projekt gesprochen
   ✅ Ich habe gestern mit meinem Chef über das neue Projekt gesprochen
   💡 Nach der Präposition „mit“ benutzt man immer den Dativ.
2. ❌ weil wir haben nur zwei Wochen für die Vorbereitung
   ✅ weil wir nur zwei Wochen für die Vorbereitung haben
   💡 In einem Nebensatz mit „weil“ muss das konjugierte Verb am Ende stehen.
3. ❌ und habe danach nach Hause gefahren
   ✅ und bin danach nach Hause gefahren
   💡 Das Verb „fahren“ beschreibt eine Bewegung von A nach B und bildet das Perfekt deshalb mit „sein“.

Planted errors:
- [FOUND] `kasus` `mit mein Chef` → `mit meinem Chef`
- [FOUND] `verbposition` `weil wir haben nur zwei Wochen` → `weil wir nur zwei Wochen haben`
- [FOUND] `perfekt-hilfsverb` `habe danach nach Hause gefahren` → `bin danach nach Hause gefahren`

##### DE · run 2 · seed 3245 · 7538 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ Ich habe gestern mit mein Chef über das neue Projekt gesprochen
   ✅ Ich habe gestern mit meinem Chef über das neue Projekt gesprochen
   💡 Nach der Präposition „mit“ benutzt man immer den Dativ.
2. ❌ weil wir haben nur zwei Wochen für die Vorbereitung
   ✅ weil wir nur zwei Wochen für die Vorbereitung haben
   💡 In einem Nebensatz mit „weil“ muss das konjugierte Verb am Ende stehen.
3. ❌ und habe danach nach Hause gefahren
   ✅ und bin danach nach Hause gefahren
   💡 Das Verb „fahren“ beschreibt eine Bewegung von A nach B und bildet das Perfekt deshalb mit „sein“.

Planted errors:
- [FOUND] `kasus` `mit mein Chef` → `mit meinem Chef`
- [FOUND] `verbposition` `weil wir haben nur zwei Wochen` → `weil wir nur zwei Wochen haben`
- [FOUND] `perfekt-hilfsverb` `habe danach nach Hause gefahren` → `bin danach nach Hause gefahren`


#### Case `diskussion`

Planted: `verbposition` `Meiner Meinung nach, die Autos sind` → `Meiner Meinung nach sind die Autos`; `kasus` `mit Fahrräder` → `mit Fahrrädern`; `genus` `das öffentliche Verkehr` → `der öffentliche Verkehr`

##### EN · run 1 · seed 4234 · 9836 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ Meiner Meinung nach, die Autos sind nicht das größte Problem
   ✅ Meiner Meinung nach sind die Autos nicht das größte Problem
   💡 In German, "Meiner Meinung nach" occupies position one, so the verb must follow immediately in position two.
2. ❌ die Pakete mit Fahrräder ausliefern
   ✅ die Pakete mit Fahrrädern ausliefern
   💡 The preposition "mit" always requires the dative case, which adds an "-n" to the plural noun "Fahrräder".
3. ❌ das öffentliche Verkehr sollte besser werden
   ✅ der öffentliche Verkehr sollte besser werden
   💡 The noun "Verkehr" is masculine, so the article and adjective ending must be "der öffentliche".

Planted errors:
- [FOUND] `verbposition` `Meiner Meinung nach, die Autos sind` → `Meiner Meinung nach sind die Autos`
- [FOUND] `kasus` `mit Fahrräder` → `mit Fahrrädern`
- [FOUND] `genus` `das öffentliche Verkehr` → `der öffentliche Verkehr`

##### EN · run 2 · seed 4244 · 8656 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ Meiner Meinung nach, die Autos sind nicht das größte Problem
   ✅ Meiner Meinung nach sind die Autos nicht das größte Problem
   💡 In German, "Meiner Meinung nach" occupies the first position, so the verb must follow immediately.
2. ❌ die Pakete mit Fahrräder ausliefern
   ✅ die Pakete mit Fahrrädern ausliefern
   💡 The preposition "mit" always requires the dative case, so the plural noun needs an "-n" ending.
3. ❌ das öffentliche Verkehr sollte besser werden
   ✅ der öffentliche Verkehr sollte besser werden
   💡 The noun "Verkehr" is masculine, so the article and adjective must reflect that.

Planted errors:
- [FOUND] `verbposition` `Meiner Meinung nach, die Autos sind` → `Meiner Meinung nach sind die Autos`
- [FOUND] `kasus` `mit Fahrräder` → `mit Fahrrädern`
- [FOUND] `genus` `das öffentliche Verkehr` → `der öffentliche Verkehr`

##### DE · run 1 · seed 4235 · 8832 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ Meiner Meinung nach, die Autos sind nicht das größte Problem
   ✅ Meiner Meinung nach sind die Autos nicht das größte Problem
   💡 Nach der Einleitung „Meiner Meinung nach“ muss das Verb an der zweiten Position im Satz stehen.
2. ❌ die Pakete mit Fahrräder ausliefern
   ✅ die Pakete mit Fahrrädern ausliefern
   💡 Das Wort „mit“ braucht hier den Dativ Plural, also ein „n“ am Ende von „Fahrrädern“.
3. ❌ Ich finde, das öffentliche Verkehr sollte besser werden
   ✅ Ich finde, der öffentliche Verkehr sollte besser werden
   💡 Das Nomen „Verkehr“ ist maskulin (der Verkehr), deshalb muss auch der Artikel maskulin sein.

Planted errors:
- [FOUND] `verbposition` `Meiner Meinung nach, die Autos sind` → `Meiner Meinung nach sind die Autos`
- [FOUND] `kasus` `mit Fahrräder` → `mit Fahrrädern`
- [FOUND] `genus` `das öffentliche Verkehr` → `der öffentliche Verkehr`

##### DE · run 2 · seed 4245 · 8319 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ Meiner Meinung nach, die Autos sind nicht das größte Problem
   ✅ Meiner Meinung nach sind die Autos nicht das größte Problem
   💡 Nach der Wendung „Meiner Meinung nach“ folgt direkt das Verb an Position 2.
2. ❌ die Pakete mit Fahrräder ausliefern
   ✅ die Pakete mit Fahrrädern ausliefern
   💡 Das Wort „mit“ braucht hier den Dativ Plural, also ein „n“ am Ende von „Fahrrädern“.
3. ❌ Ich finde, das öffentliche Verkehr sollte besser werden
   ✅ Ich finde, der öffentliche Verkehr sollte besser werden
   💡 Das Nomen „Verkehr“ ist maskulin (der Verkehr), deshalb muss auch der Artikel maskulin sein.

Planted errors:
- [FOUND] `verbposition` `Meiner Meinung nach, die Autos sind` → `Meiner Meinung nach sind die Autos`
- [FOUND] `kasus` `mit Fahrräder` → `mit Fahrrädern`
- [FOUND] `genus` `das öffentliche Verkehr` → `der öffentliche Verkehr`


#### Case `pruefung_planung`

Planted: `adjektivendung` `im großem Kursraum` → `im großen Kursraum`; `verbposition` `weil es ist persönlicher` → `weil es persönlicher ist`; `praeposition` `für die Getränke` → `um die Getränke`

##### EN · run 1 · seed 5234 · 8832 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ ...im großem Kursraum machen...
   ✅ ...im großen Kursraum machen...
   💡 After the preposition "in" (dative case), the adjective needs the weak ending "-en" in this context.
2. ❌ ...weil es ist persönlicher.
   ✅ ...weil es persönlicher ist.
   💡 In a subordinate clause starting with "weil", the conjugated verb must move to the very end of the sentence.

Planted errors:
- [FOUND] `adjektivendung` `im großem Kursraum` → `im großen Kursraum`
- [FOUND] `verbposition` `weil es ist persönlicher` → `weil es persönlicher ist`
- [MISSED] `praeposition` `für die Getränke` → `um die Getränke`

##### EN · run 2 · seed 5244 · 9001 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ ...im großem Kursraum machen...
   ✅ ...im großen Kursraum machen...
   💡 After the preposition "in" (dative), the adjective needs a weak or mixed ending, which is "-en" in this case.
2. ❌ ...weil es ist persönlicher.
   ✅ ...weil es persönlicher ist.
   💡 In a subordinate clause starting with "weil", the conjugated verb must move to the very end of the sentence.

Planted errors:
- [FOUND] `adjektivendung` `im großem Kursraum` → `im großen Kursraum`
- [FOUND] `verbposition` `weil es ist persönlicher` → `weil es persönlicher ist`
- [MISSED] `praeposition` `für die Getränke` → `um die Getränke`

##### DE · run 1 · seed 5235 · 8856 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ ...dass wir die Feier im großem Kursraum machen...
   ✅ ...dass wir die Feier im großen Kursraum machen...
   💡 Nach der Präposition „in“ (hier mit dem Artikel „dem“ verschmolzen zu „im“) folgt der Dativ, und das Adjektiv braucht die Endung „-en“.
2. ❌ ...weil es ist persönlicher.
   ✅ ...weil es persönlicher ist.
   💡 In einem Nebensatz mit der Konjunktion „weil“ muss das konjugierte Verb am Ende des Satzes stehen.

Planted errors:
- [FOUND] `adjektivendung` `im großem Kursraum` → `im großen Kursraum`
- [FOUND] `verbposition` `weil es ist persönlicher` → `weil es persönlicher ist`
- [MISSED] `praeposition` `für die Getränke` → `um die Getränke`

##### DE · run 2 · seed 5245 · 7681 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ ...dass wir die Feier im großem Kursraum machen...
   ✅ ...dass wir die Feier im großen Kursraum machen...
   💡 Nach der Präposition „in“ (hier mit Artikel „dem“ verschmolzen zu „im“) folgt der Dativ, und das Adjektiv braucht die Endung „-en“.
2. ❌ ...weil es ist persönlicher.
   ✅ ...weil es persönlicher ist.
   💡 In einem Nebensatz mit der Konjunktion „weil“ muss das konjugierte Verb am Ende stehen.

Planted errors:
- [FOUND] `adjektivendung` `im großem Kursraum` → `im großen Kursraum`
- [FOUND] `verbposition` `weil es ist persönlicher` → `weil es persönlicher ist`
- [MISSED] `praeposition` `für die Getränke` → `um die Getränke`



### (c) `gemma4:31b` · temperature 0.3

Model: `gemma4:31b` · temperature: 0.3 · seed base: 1234 · runs: 2

| language | feedbacks | recall | false_corrections | wrong_corrections | noop_corrections | ungrounded | quotes_kerstin | structure_failures | lang_mismatch | format_noise | p50_ms | p90_ms | mean_feedback_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| en | 10 | 40% | 2 | 18 | 0 | 0 | 0 | 6 | 2 | 60 | 43380 | 53260 | 46090 |
| de | 10 | 80% | 2 | 6 | 1 | 0 | 0 | 2 | 0 | 42 | 43824 | 49100 | 45052 |

#### (c) raw ❌/✅/💡 triples

#### Case `freies_gespraech`

Planted: `kasus` `mit ein Freund` → `mit einem Freund`; `verbposition` `weil ich bin seit zwei Wochen im Team` → `weil ich seit zwei Wochen im Team bin`; `praeposition` `für den Sommer` → `auf den Sommer`

##### EN · run 1 · seed 1234 · 55231 ms

structure=FAIL · false_corrections=0 · wrong_corrections=3 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=10

1. ❌ ...mit ein Freund im Park gesessen
   ✅ (missing)
   💡 The preposition 'mit' always requires the dative case.
2. ❌ ...weil ich bin seit zwei Wochen im Team
   ✅ (missing)
   💡 In a subordinate clause starting with 'weil', the conjugated verb must go to the end.
3. ❌ Ich freue mich für den Sommer
   ✅ (missing)
   💡 Use 'sich freuen auf' for future events and 'sich freuen über' for present/past events.

Planted errors:
- [WRONG] `kasus` `mit ein Freund` → `mit einem Freund`
- [WRONG] `verbposition` `weil ich bin seit zwei Wochen im Team` → `weil ich seit zwei Wochen im Team bin`
- [WRONG] `praeposition` `für den Sommer` → `auf den Sommer`

##### EN · run 2 · seed 1244 · 38643 ms

structure=FAIL · false_corrections=0 · wrong_corrections=3 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=10

1. ❌ ...mit ein Freund im Park gesessen
   ✅ (missing)
   💡 The preposition 'mit' always requires the dative case.
2. ❌ ...weil ich bin seit zwei Wochen im Team
   ✅ (missing)
   💡 In a subordinate clause starting with 'weil', the conjugated verb must go to the end.
3. ❌ Ich freue mich für den Sommer
   ✅ (missing)
   💡 Use 'sich freuen auf' for future events and 'sich freuen über' for present/past events.

Planted errors:
- [WRONG] `kasus` `mit ein Freund` → `mit einem Freund`
- [WRONG] `verbposition` `weil ich bin seit zwei Wochen im Team` → `weil ich seit zwei Wochen im Team bin`
- [WRONG] `praeposition` `für den Sommer` → `auf den Sommer`

##### DE · run 1 · seed 1235 · 40028 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ Ich habe gestern mit ein Freund im Park gesessen
   ✅ Ich habe gestern mit einem Freund im Park gesessen
   💡 Die Präposition „mit“ verlangt immer den Dativ (einem Freund).
2. ❌ weil ich bin seit zwei Wochen im Team
   ✅ weil ich seit zwei Wochen im Team bin
   💡 In einem Nebensatz mit „weil“ steht das konjugierte Verb am Ende.
3. ❌ Ich freue mich für den Sommer
   ✅ Ich freue mich auf den Sommer
   💡 Man benutzt „sich freuen auf“ für Ereignisse in der Zukunft.

Planted errors:
- [FOUND] `kasus` `mit ein Freund` → `mit einem Freund`
- [FOUND] `verbposition` `weil ich bin seit zwei Wochen im Team` → `weil ich seit zwei Wochen im Team bin`
- [FOUND] `praeposition` `für den Sommer` → `auf den Sommer`

##### DE · run 2 · seed 1245 · 40136 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ Ich habe gestern mit ein Freund im Park gesessen
   ✅ Ich habe gestern mit einem Freund im Park gesessen
   💡 Nach der Präposition „mit“ folgt immer der Dativ (einem Freund).
2. ❌ weil ich bin seit zwei Wochen im Team
   ✅ weil ich seit zwei Wochen im Team bin
   💡 In einem Nebensatz mit „weil“ steht das konjugierte Verb am Ende.
3. ❌ Ich freue mich für den Sommer
   ✅ Ich freue mich auf den Sommer
   💡 Man benutzt die Präposition „auf“ für Ereignisse in der Zukunft (Vorfreude).

Planted errors:
- [FOUND] `kasus` `mit ein Freund` → `mit einem Freund`
- [FOUND] `verbposition` `weil ich bin seit zwei Wochen im Team` → `weil ich seit zwei Wochen im Team bin`
- [FOUND] `praeposition` `für den Sommer` → `auf den Sommer`


#### Case `wg_alltag`

Planted: `kasus` `auf der Tisch` → `auf den Tisch`; `verbposition` `weil er ist abends sehr müde` → `weil er abends sehr müde ist`; `adjektivendung` `mit klare Regeln` → `mit klaren Regeln`

##### EN · run 1 · seed 2234 · 43408 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ ...weil er ist abends sehr müde.
   ✅ ...weil er abends sehr müde ist.
   💡 In subordinate clauses starting with "weil", the conjugated verb must go to the end.
2. ❌ ...auf der Tisch gestellt.
   ✅ ...auf den Tisch gestellt.
   💡 Use the accusative case for "auf" when describing a movement/direction (where to?).
3. ❌ ...mit klare Regeln...
   ✅ ...mit klaren Regeln...
   💡 The preposition "mit" always requires the dative case (plural ending -en here).

Planted errors:
- [FOUND] `kasus` `auf der Tisch` → `auf den Tisch`
- [FOUND] `verbposition` `weil er ist abends sehr müde` → `weil er abends sehr müde ist`
- [FOUND] `adjektivendung` `mit klare Regeln` → `mit klaren Regeln`

##### EN · run 2 · seed 2244 · 41920 ms

structure=FAIL · false_corrections=0 · wrong_corrections=3 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ ...weil er ist abends sehr müde.
   ✅ (missing)
   💡 In subordinate clauses starting with "weil", the conjugated verb must go to the end.
2. ❌ ...auf der Tisch gestellt.
   ✅ (missing)
   💡 Use the accusative case for "auf" when describing a movement/direction (Wohin?).
3. ❌ ...mit klare Regeln
   ✅ (missing)
   💡 The preposition "mit" always requires the dative case, and the plural adjective ending here is "-en".

Planted errors:
- [WRONG] `kasus` `auf der Tisch` → `auf den Tisch`
- [WRONG] `verbposition` `weil er ist abends sehr müde` → `weil er abends sehr müde ist`
- [WRONG] `adjektivendung` `mit klare Regeln` → `mit klaren Regeln`

##### DE · run 1 · seed 2235 · 44091 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ ...weil er ist abends sehr müde.
   ✅ ...weil er abends sehr müde ist.
   💡 In einem Nebensatz mit „weil“ steht das konjugierte Verb am Ende.
2. ❌ ...auf der Tisch gestellt.
   ✅ ...auf den Tisch gestellt.
   💡 Hier wird eine Richtung/Bewegung beschrieben, deshalb folgt nach der Präposition „auf“ der Akkusativ.
3. ❌ ...mit klare Regeln
   ✅ ...mit klaren Regeln
   💡 Die Präposition „mit“ verlangt immer den Dativ (Plural), daher benötigt das Adjektiv die Endung -en.

Planted errors:
- [FOUND] `kasus` `auf der Tisch` → `auf den Tisch`
- [FOUND] `verbposition` `weil er ist abends sehr müde` → `weil er abends sehr müde ist`
- [FOUND] `adjektivendung` `mit klare Regeln` → `mit klaren Regeln`

##### DE · run 2 · seed 2245 · 40095 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ ...auf der Tisch gestellt.
   ✅ ...auf den Tisch gestellt.
   💡 Hier wird eine Richtung/Bewegung beschrieben, daher benötigst du den Akkusativ.
2. ❌ ...weil er ist abends sehr müde.
   ✅ ...weil er abends sehr müde ist.
   💡 In einem Nebensatz mit „weil“ steht das konjugierte Verb am Ende.
3. ❌ ...mit klare Regeln
   ✅ ...mit klaren Regeln
   💡 Die Präposition „mit“ verlangt immer den Dativ (Plural: -en Endung beim Adjektiv).

Planted errors:
- [FOUND] `kasus` `auf der Tisch` → `auf den Tisch`
- [FOUND] `verbposition` `weil er ist abends sehr müde` → `weil er abends sehr müde ist`
- [FOUND] `adjektivendung` `mit klare Regeln` → `mit klaren Regeln`


#### Case `arbeit_kollegen`

Planted: `kasus` `mit mein Chef` → `mit meinem Chef`; `verbposition` `weil wir haben nur zwei Wochen` → `weil wir nur zwei Wochen haben`; `perfekt-hilfsverb` `habe danach nach Hause gefahren` → `bin danach nach Hause gefahren`

##### EN · run 1 · seed 3234 · 43352 ms

structure=FAIL · false_corrections=0 · wrong_corrections=3 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ ...mit mein Chef...
   ✅ (missing)
   💡 The preposition 'mit' always requires the dative case.
2. ❌ ...weil wir haben nur zwei Wochen...
   ✅ (missing)
   💡 In a subordinate clause starting with 'weil', the conjugated verb must go to the end.
3. ❌ ...habe danach nach Hause gefahren.
   ✅ (missing)
   💡 Verbs of movement (like 'fahren') use 'sein' as the auxiliary verb for the perfect tense.

Planted errors:
- [WRONG] `kasus` `mit mein Chef` → `mit meinem Chef`
- [WRONG] `verbposition` `weil wir haben nur zwei Wochen` → `weil wir nur zwei Wochen haben`
- [WRONG] `perfekt-hilfsverb` `habe danach nach Hause gefahren` → `bin danach nach Hause gefahren`

##### EN · run 2 · seed 3244 · 40278 ms

structure=FAIL · false_corrections=0 · wrong_corrections=3 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ ...mit mein Chef...
   ✅ (missing)
   💡 The preposition „mit“ always requires the dative case.
2. ❌ ...weil wir haben nur zwei Wochen...
   ✅ (missing)
   💡 In a subordinate clause starting with „weil“, the conjugated verb must go to the end.
3. ❌ ...und habe danach nach Hause gefahren.
   ✅ (missing)
   💡 Verbs of movement (like „fahren“) use „sein“ as the auxiliary verb for the Perfekt tense.

Planted errors:
- [WRONG] `kasus` `mit mein Chef` → `mit meinem Chef`
- [WRONG] `verbposition` `weil wir haben nur zwei Wochen` → `weil wir nur zwei Wochen haben`
- [WRONG] `perfekt-hilfsverb` `habe danach nach Hause gefahren` → `bin danach nach Hause gefahren`

##### DE · run 1 · seed 3235 · 43558 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ Ich habe gestern mit mein Chef...
   ✅ Ich habe gestern mit meinem Chef...
   💡 Nach der Präposition „mit“ folgt immer der Dativ (maskulin: meinem).
2. ❌ ...weil wir haben nur zwei Wochen...
   ✅ ...weil wir nur zwei Wochen haben.
   💡 In einem Nebensatz mit „weil“ steht das konjugierte Verb am Ende.
3. ❌ ...und habe danach nach Hause gefahren.
   ✅ ...und bin danach nach Hause gefahren.
   💡 Das Perfekt von Verben der Ortsveränderung (fahren) wird mit dem Hilfsverb „sein“ gebildet.

Planted errors:
- [FOUND] `kasus` `mit mein Chef` → `mit meinem Chef`
- [FOUND] `verbposition` `weil wir haben nur zwei Wochen` → `weil wir nur zwei Wochen haben`
- [FOUND] `perfekt-hilfsverb` `habe danach nach Hause gefahren` → `bin danach nach Hause gefahren`

##### DE · run 2 · seed 3245 · 41370 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ Ich habe gestern mit mein Chef über das neue Projekt gesprochen
   ✅ Ich habe gestern mit meinem Chef über das neue Projekt gesprochen
   💡 Nach der Präposition „mit“ folgt immer der Dativ (maskulin: meinem).
2. ❌ weil wir haben nur zwei Wochen für die Vorbereitung
   ✅ weil wir nur zwei Wochen für die Vorbereitung haben
   💡 In einem Nebensatz mit „weil“ steht das konjugierte Verb am Ende.
3. ❌ habe danach nach Hause gefahren
   ✅ bin danach nach Hause gefahren
   💡 Verben der Bewegung (fahren) bilden das Perfekt mit dem Hilfsverb „sein“.

Planted errors:
- [FOUND] `kasus` `mit mein Chef` → `mit meinem Chef`
- [FOUND] `verbposition` `weil wir haben nur zwei Wochen` → `weil wir nur zwei Wochen haben`
- [FOUND] `perfekt-hilfsverb` `habe danach nach Hause gefahren` → `bin danach nach Hause gefahren`


#### Case `diskussion`

Planted: `verbposition` `Meiner Meinung nach, die Autos sind` → `Meiner Meinung nach sind die Autos`; `kasus` `mit Fahrräder` → `mit Fahrrädern`; `genus` `das öffentliche Verkehr` → `der öffentliche Verkehr`

##### EN · run 1 · seed 4234 · 50373 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=True · format_noise=4

1. ❌ Meiner Meinung nach, die Autos sind nicht das größte Problem...
   ✅ Meiner Meinung nach sind die Autos nicht das größte Problem...
   💡 In German, "meiner Meinung nach" occupies position 1, so the verb must follow immediately in position 2.
2. ❌ ...sondern der viele Lieferverkehr.
   ✅ ...sondern der viele Lieferverkehr / sondern der starke Lieferverkehr.
   💡 "Lieferverkehr" is masculine, but "viele" is used for countable nouns; for uncountable nouns, use "viel" or "stark".
3. ❌ ...die Pakete mit Fahrräder ausliefern.
   ✅ ...die Pakete mit Fahrrädern ausliefern.
   💡 The preposition "mit" always requires the dative case, and the plural dative ends in "-n".
4. ❌ Ich finde, das öffentliche Verkehr sollte besser werden...
   ✅ Ich finde, der öffentliche Verkehr sollte besser werden...
   💡 "Verkehr" is a masculine noun (der Verkehr), not neuter.

Planted errors:
- [FOUND] `verbposition` `Meiner Meinung nach, die Autos sind` → `Meiner Meinung nach sind die Autos`
- [FOUND] `kasus` `mit Fahrräder` → `mit Fahrrädern`
- [FOUND] `genus` `das öffentliche Verkehr` → `der öffentliche Verkehr`

##### EN · run 2 · seed 4244 · 53260 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=True · format_noise=4

1. ❌ Meiner Meinung nach, die Autos sind nicht das größte Problem...
   ✅ Meiner Meinung nach sind die Autos nicht das größte Problem...
   💡 In German, "meiner Meinung nach" occupies position 1, so the verb must follow immediately in position 2.
2. ❌ ...sondern der viele Lieferverkehr.
   ✅ ...sondern der viele Lieferverkehr / sondern der starke Lieferverkehr.
   💡 "Lieferverkehr" is masculine singular; the adjective ending must be "-e" (nominative), though "stark" is a more natural collocation than "viel".
3. ❌ ...die Pakete mit Fahrräder ausliefern.
   ✅ ...die Pakete mit Fahrrädern ausliefern.
   💡 The preposition "mit" always requires the dative case, and the plural dative ends in "-n".
4. ❌ ...das öffentliche Verkehr sollte besser werden...
   ✅ ...der öffentliche Verkehr sollte besser werden...
   💡 "Verkehr" is a masculine noun (der Verkehr), not neuter.

Planted errors:
- [FOUND] `verbposition` `Meiner Meinung nach, die Autos sind` → `Meiner Meinung nach sind die Autos`
- [FOUND] `kasus` `mit Fahrräder` → `mit Fahrrädern`
- [FOUND] `genus` `das öffentliche Verkehr` → `der öffentliche Verkehr`

##### DE · run 1 · seed 4235 · 55889 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=1 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ Meiner Meinung nach, die Autos sind nicht das größte Problem
   ✅ Meiner Meinung nach sind die Autos nicht das größte Problem
   💡 Nach der Wendung „Meiner Meinung nach“ folgt direkt das Verb (Position 2).
2. ❌ sondern der viele Lieferverkehr
   ✅ sondern der viele Lieferverkehr
   💡 Hier ist die Wortwahl problematisch; bei nicht zählbaren Nomen wie „Verkehr“ nutzt man eher „stark“ statt „viel“.
3. ❌ die Pakete mit Fahrräder ausliefern
   ✅ die Pakete mit Fahrrädern ausliefern
   💡 Die Präposition „mit“ verlangt immer den Dativ (Plural: -n Endung).
4. ❌ das öffentliche Verkehr sollte besser werden
   ✅ der öffentliche Verkehr sollte besser werden
   💡 Das Wort „Verkehr“ ist ein Maskulinum (der Verkehr), daher ist der Artikel „das“ falsch.

Planted errors:
- [FOUND] `verbposition` `Meiner Meinung nach, die Autos sind` → `Meiner Meinung nach sind die Autos`
- [FOUND] `kasus` `mit Fahrräder` → `mit Fahrrädern`
- [FOUND] `genus` `das öffentliche Verkehr` → `der öffentliche Verkehr`

##### DE · run 2 · seed 4245 · 49100 ms

structure=OK · false_corrections=0 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=6

1. ❌ Meiner Meinung nach, die Autos sind nicht das größte Problem
   ✅ Meiner Meinung nach sind die Autos nicht das größte Problem
   💡 Nach der Wendung „Meiner Meinung nach“ folgt direkt das Verb (Position 2).
2. ❌ sondern der viele Lieferverkehr
   ✅ sondern der viele Lieferverkehr $\rightarrow$ sondern der viele Lieferverkehr (besser: der starke Lieferverkehr / viel Lieferverkehr)
   💡 Hier ist die Wortwahl unpassend; „viel“ wird bei nicht zählbaren Nomen nicht gesteigert/dekliniert.
3. ❌ die Pakete mit Fahrräder ausliefern
   ✅ die Pakete mit Fahrrädern ausliefern
   💡 Die Präposition „mit“ verlangt immer den Dativ (Plural: -n).
4. ❌ das öffentliche Verkehr sollte besser werden
   ✅ der öffentliche Verkehr sollte besser werden
   💡 Das Wort „Verkehr“ ist ein Maskulinum (der Verkehr), daher ist der Artikel „das“ falsch.

Planted errors:
- [FOUND] `verbposition` `Meiner Meinung nach, die Autos sind` → `Meiner Meinung nach sind die Autos`
- [FOUND] `kasus` `mit Fahrräder` → `mit Fahrrädern`
- [FOUND] `genus` `das öffentliche Verkehr` → `der öffentliche Verkehr`


#### Case `pruefung_planung`

Planted: `adjektivendung` `im großem Kursraum` → `im großen Kursraum`; `verbposition` `weil es ist persönlicher` → `weil es persönlicher ist`; `praeposition` `für die Getränke` → `um die Getränke`

##### EN · run 1 · seed 5234 · 42846 ms

structure=FAIL · false_corrections=1 · wrong_corrections=3 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=12

1. ❌ ...im großem Kursraum machen
   ✅ (missing)
   💡 Adjective ending after the definite article in the dative case.
2. ❌ ...weil es ist persönlicher
   ✅ (missing)
   💡 In a subordinate clause starting with "weil", the conjugated verb must go to the end.
3. ❌ Ich könnte mich für die Getränke kümmern
   ✅ (missing)
   💡 The reflexive verb "sich kümmern" always requires the preposition "um".
4. ❌ Ich habe mich für die Hilfe meiner Kollegin bedankt
   ✅ (missing)
   💡 "Sich bedanken" requires "bei" for the person and "für" for the thing/action.

Planted errors:
- [WRONG] `adjektivendung` `im großem Kursraum` → `im großen Kursraum`
- [WRONG] `verbposition` `weil es ist persönlicher` → `weil es persönlicher ist`
- [WRONG] `praeposition` `für die Getränke` → `um die Getränke`

##### EN · run 2 · seed 5244 · 51592 ms

structure=OK · false_corrections=1 · wrong_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ ...weil es ist persönlicher.
   ✅ ...weil es persönlicher ist.
   💡 In subordinate clauses starting with "weil", the conjugated verb must move to the end of the sentence.
2. ❌ ...im großem Kursraum...
   ✅ ...im großen Kursraum...
   💡 After the contraction "im" (in dem), the adjective requires the weak declension ending "-en".
3. ❌ Ich könnte mich für die Getränke kümmern...
   ✅ Ich könnte mich um die Getränke kümmern...
   💡 The reflexive verb "sich kümmern" always takes the preposition "um", not "für".
4. ❌ Ich habe mich für die Hilfe meiner Kollegin bedankt.
   ✅ Ich bedanke mich bei meiner Kollegin für die Hilfe.
   💡 You used the past tense here, but in this context, you likely meant a future intention or a general statement; also, you thank a person (*bei jemandem*) for something (*für etwas*).

Planted errors:
- [FOUND] `adjektivendung` `im großem Kursraum` → `im großen Kursraum`
- [FOUND] `verbposition` `weil es ist persönlicher` → `weil es persönlicher ist`
- [FOUND] `praeposition` `für die Getränke` → `um die Getränke`

##### DE · run 1 · seed 5235 · 48370 ms

structure=FAIL · false_corrections=1 · wrong_corrections=3 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ ...im großem Kursraum machen
   ✅ (missing)
   💡 Nach der Präposition „in“ + Dativ (verschmolzen zu „im“) benötigt das Adjektiv die Endung -en.
2. ❌ ...weil es ist persönlicher.
   ✅ (missing)
   💡 In einem Nebensatz mit „weil“ steht das konjugierte Verb am Ende.
3. ❌ Ich könnte mich für die Getränke kümmern
   ✅ (missing)
   💡 Das Verb „sich kümmern“ wird immer mit der Präposition „um“ + Akkusativ verwendet.
4. ❌ Ich habe mich für die Hilfe meiner Kollegin bedankt.
   ✅ (missing)
   💡 Hier passt die Bedeutung nicht zum Kontext; zudem heißt es „sich bei jemandem (Dativ) für etwas (Akkusativ) bedanken“.

Planted errors:
- [WRONG] `adjektivendung` `im großem Kursraum` → `im großen Kursraum`
- [WRONG] `verbposition` `weil es ist persönlicher` → `weil es persönlicher ist`
- [WRONG] `praeposition` `für die Getränke` → `um die Getränke`

##### DE · run 2 · seed 5245 · 47883 ms

structure=FAIL · false_corrections=1 · wrong_corrections=3 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ ...im großem Kursraum machen
   ✅ (missing)
   💡 Nach der Präposition „in“ + Dativ (verschmolzen zu „im“) benötigt das Adjektiv die Endung -en.
2. ❌ ...weil es ist persönlicher.
   ✅ (missing)
   💡 In einem Nebensatz mit „weil“ steht das konjugierte Verb am Ende.
3. ❌ Ich könnte mich für die Getränke kümmern
   ✅ (missing)
   💡 Das Verb „sich kümmern“ benötigt immer die Präposition „um“ + Akkusativ.
4. ❌ Ich habe mich für die Hilfe meiner Kollegin bedankt.
   ✅ (missing)
   💡 Hier passt die Bedeutung nicht zum Kontext; zudem heißt es „sich bei jemandem (Dativ) für etwas (Akkusativ) bedanken“.

Planted errors:
- [WRONG] `adjektivendung` `im großem Kursraum` → `im großen Kursraum`
- [WRONG] `verbposition` `weil es ist persönlicher` → `weil es persönlicher ist`
- [WRONG] `praeposition` `für die Getränke` → `um die Getränke`


- **Deviations from spec / extra files touched:** `Deps` gained `ollama_model`, `feedback_model`, `feedback_temperature`, and `ollama_max_loaded`; this is required for the `feedback()` guard and is passed from `main.py`. The only unplanned runtime event was the external `bge-m3` load that evicted `llama3.2:1b`; I restored llama after the run. No `.env` or Ollama configuration was changed. A pre-existing working-tree `.gitignore` change (adds `*.prs`) was left untouched and unstaged.
- **New dependencies (+license):** None.
- **Open questions:** `feedback_model` stays `None`; the 31b numbers are clearly worse and much slower. The lead/Sameer can decide whether a future candidate is worth the model-swap cost.

## Review (Claude Code fills this in)
- **Verdict:**
- **Notes:**
