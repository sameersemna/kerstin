# T005 — Model warm-up on session start + random seed per request

**Branch:** `task/T005-warmup-seed` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
1. When the learner presses "Gespräch starten" and the model was unloaded (idle > `keep_alive`), the first learner turn no longer waits ~7 s for the model to load.
2. Kerstin stops giving word-for-word identical replies to identical input across sessions.

## Context
- Cold first turn: `llm_first_token_ms` ≈ 7.1–7.4 s vs ≈ 0.5 s warm (T001, T032 review). The model loads only when the first learner utterance arrives.
- The lead verified (T002 review) that Ollama 0.34.2 **samples deterministically when no `seed` is sent**: the same messages give the same output even at `temperature` 0.8. And `qwen3:14b` gives the same reply to a repeated sentence even with a different history. Today `llm.py` sends no seed.
- `keep_alive` (default `10m`) must still let the model unload when idle. The warm-up only moves the load earlier; it doesn't keep the model resident any longer.

## Hard rules
- Same as before: port **8771** for test servers; don't touch 8770, the Whisper server (`/load` forbidden), or Ollama config; no model pulls.
- **Don't force-unload the model** (`keep_alive: 0`): other tools may be using `qwen3:14b`. To test a cold start, wait until `ollama ps` no longer lists it (keep_alive expiry), and do other work in the meantime.
- Thermal guard as in the smoke test.

## Spec
1. **Seed** (`backend/kerstin/llm.py`, `backend/kerstin/config.py`):
   - New setting `llm_seed: int | None = None`.
   - In `OllamaLLM._payload`: if `llm_seed` is set, send `options.seed = llm_seed` (reproducible benches). Otherwise send a fresh `random.randrange(1, 2**31)` per request.
   - This applies to `stream_chat` and `chat`. No latency impact.
2. **Warm-up** (`llm.py`, `session.py`, `config.py`):
   - New setting `llm_warmup: bool = True`.
   - `OllamaLLM.warmup(messages: list[Message]) -> None`: a non-streaming `POST /api/chat` with the given messages, `num_predict: 1`, the same `model`, `keep_alive`, `num_ctx` and `think` as normal requests. This loads the model and caches the prompt prefix. It must never raise: log a warning on any error, including timeouts, and return.
   - `Session.start()`: if `llm_warmup` is on, start `asyncio.create_task(self.deps.llm.warmup([system, opener-as-assistant]))` **before** speaking the opener, so it runs while the opener is synthesized and played. Don't await it in `start()`.
   - Keep a reference on the session. `close()` cancels it if still running.
   - A learner turn that arrives while the warm-up is still running just proceeds; Ollama queues it. Don't add waiting logic.
   - Pass the setting through `Deps` (e.g. `Deps.llm_warmup: bool = True`, set in `main.py` from settings). Keep `Session` free of global settings.
3. **Tests** (no network):
   - `backend/tests/test_llm.py` (new), using `httpx.MockTransport` for `OllamaLLM`:
     - (a) without `llm_seed`, two payloads have `options.seed` set and different;
     - (b) with `llm_seed=42`, `options.seed == 42`;
     - (c) `warmup` sends `num_predict: 1`, `stream: false` and the given messages;
     - (d) `warmup` swallows an HTTP 500 and a `httpx.ConnectError`.
     - Allow an injected client: `OllamaLLM(s, client: httpx.AsyncClient | None = None)`, same pattern as `WhisperCppSTT`.
   - `backend/tests/test_session.py`:
     - add `warmup` to `FakeLLM` and record its calls;
     - new test: `start()` triggers exactly one warm-up with the system prompt + opener, and the opener is still sent;
     - new test: with `llm_warmup=False` there's no warm-up call;
     - new test: a `warmup` that hangs (`asyncio.sleep(10)`) doesn't delay the opener, and `close()` cancels it.
4. **Smoke test:** add `--first-delay SECONDS` (default `0`) to `scripts/smoke_test.py`. It sleeps after the opener and before turn 1, simulating the learner thinking. Default behavior is unchanged.
5. **`.env.example`:** add commented `KERSTIN_LLM_WARMUP=true` and `# KERSTIN_LLM_SEED=` lines with one-line explanations. Note that a fixed seed is for benches only.
6. **Measure:**
   - (a) **Cold:** once `ollama ps` doesn't list `qwen3:14b`, start the 8771 server and run `smoke_test.py --url wss://localhost:8771/ws --first-delay 6`. Report turn 1 `llm_first_token_ms` and `first_audio_ms`, and compare with T001's cold 7400 / 8781 ms.
   - (b) **Warm:** run `make bench` with `BENCH_ARGS="--runs 1"` against 8771. Report the p50 `first_audio_ms` (the warm path must not get slower: T002 high p50 was 1935 ms), and paste the (d) reply list showing that replies to identical sentences now differ between passes. Use `--runs 2` if you need two passes for that.
   - Paste `ollama ps` before and after.

## Files allowed to change
- `backend/kerstin/llm.py`, `backend/kerstin/config.py`, `backend/kerstin/session.py` (`start`/`close`/`Deps` only), `backend/kerstin/main.py` (pass `llm_warmup` into `Deps` only)
- `backend/tests/test_llm.py` (new), `backend/tests/test_session.py`
- `scripts/smoke_test.py` (`--first-delay` only)
- `.env.example`
- this task file (Worker report only)

## Out of scope
VAD, Piper voice, STT, prompt/persona changes, keeping the model loaded longer, `/api/ps` checks, and protocol changes.

## Acceptance criteria
- [ ] `make test` and `make lint` pass; the tests from spec step 3 exist and pass
- [ ] `make smoke` passes unchanged (no `--first-delay`)
- [ ] Cold-start run: turn 1 `llm_first_token_ms` < 1500 ms with `--first-delay 6` (T001 cold: 7400 ms)
- [ ] Warm bench p50 `first_audio_ms` is not worse than T002 by more than ~10 %
- [ ] Bench reply list shows different replies to the same utterance in different passes
- [ ] The model still unloads after `keep_alive`: `ollama ps` shows the normal `UNTIL` countdown, not "Forever"
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
