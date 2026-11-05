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
- **How tested:**
- **Measurements (if any):**
- **Deviations from spec / extra files touched:**
- **New dependencies (+license):**
- **Open questions:**

## Review (Claude Code fills this in)
- **Verdict:**
- **Notes:**
