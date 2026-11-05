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
- **Changed files:**
- **How tested:**
- **Measurements (if any):**
- **Deviations from spec / extra files touched:**
- **New dependencies (+license):**
- **Open questions:**

## Review (Claude Code fills this in)
- **Verdict:**
- **Notes:**
