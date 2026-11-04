# T001 — Bring-up & smoke test on the GB10

**Branch:** `task/T001-bringup` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
Kerstin runs end-to-end on the GB10 with Sameer's existing Whisper server and Ollama: speak German in the browser → hear Kerstin reply.

## Context
See `docs/STATUS.md` → "Not yet verified". The scaffold assumes an OpenAI-compatible STT endpoint and the `piper-tts` Python API; both need confirming on aarch64.

## Spec
1. `make setup`, `make voice`. If `piper-tts` fails to install on aarch64, try `pip install piper-tts` vs `piper1-gpl` naming and report what worked.
2. Identify Sameer's Whisper server: port, API shape. If it is **not** OpenAI-compatible, add a new STT class (e.g. `WhisperCppSTT` for `/inference`) behind the `STT` Protocol and a new `stt_backend` value. Do not change `HttpSTT`'s behavior.
3. Write `scripts/smoke_test.py`: connects to `/ws`, sends `start`, then sends a German test utterance (generate it with Piper itself → resample to 16 kHz Int16 PCM), and prints every message received with timestamps. Exit non-zero if no `transcript`, `reply_text` and audio frame arrive within 20 s.
4. Run `make check`, then the smoke test with Kerstin running. Paste output in the Worker report.
5. Confirm `think: false` works with the installed Ollama version (no `<think>` text in replies). Note the Ollama version.
6. Do **not** run long benchmarks (that is T002). Watch GPU temperature in `make check` before and after.

## Files allowed to change
- `scripts/smoke_test.py` (new)
- `backend/kerstin/stt.py` (only to add a new class if needed)
- `backend/kerstin/config.py` (only to add the new `stt_backend` literal / settings)
- `backend/tests/test_stt.py` (new, with fake HTTP via `httpx.MockTransport`)
- `.env.example`, `Makefile` (add `smoke` target)

## Out of scope
Persona changes, frontend changes, model comparisons.

## Acceptance criteria
- [ ] `make test` and `make lint` pass
- [ ] `make smoke` (new target) passes against a running Kerstin on the GB10
- [ ] Worker report lists: Whisper server type/port, Ollama version, piper package that worked, first-audio latency from the smoke test
- [ ] No GPU above 80 °C during the run (from `make check`)

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
