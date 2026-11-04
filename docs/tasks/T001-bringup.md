# T001 — Bring-up & smoke test on the GB10

**Branch:** `task/T001-bringup` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
Kerstin runs end-to-end on the GB10 against the existing Whisper server and Ollama, and `make smoke` proves it headlessly: German utterance in → German transcript → Kerstin's reply text + audio out.

## Context
- `docs/STATUS.md` → "Not yet verified".
- **Facts the lead checked on the GB10 (2026-11-04, read-only):**
  - Whisper is **whisper.cpp's server**, not OpenAI-compatible: `/opt/whisper/whisper-server --model .../ggml-large-v3.bin --port 8768 --host 0.0.0.0`, run by systemd unit `whisper-server.service`. Routes: `POST /inference` (multipart) and `POST /load`. `/v1/...` and `/health` return 404; `GET /` returns 200 (HTML page titled "Whisper.cpp Server").
  - It was started **without `-l`**, so its default language is English. Every request **must** send `language=de`.
  - The same Whisper server is used by another project (Sunny). whisper.cpp handles one request at a time, so STT latency can spike while Sunny is using it. Report it if you see it; don't try to fix it.
  - Ollama **0.34.2** on `127.0.0.1:11434`. `qwen3:30b-a3b` was **not** pulled at check time; Sameer pulls the model before this task starts (see Prerequisites).
  - Python 3.12.3. GPU idle at 46 °C. `nvidia-smi` memory fields show `N/A` on GB10 (unified memory), so use `free -g` / `ollama ps` for memory.

## Prerequisites (Sameer, before Kilo starts)
- `main` has an initial commit, so the task branch can be created from it.
- The model in `.env` → `KERSTIN_OLLAMA_MODEL` is pulled (default `qwen3:30b-a3b`, ~19 GB).

## Hard rules for this task (shared services)
- **Never** call `POST /load` on the Whisper server: it swaps the model for every user of that server.
- Do not restart, stop, reconfigure or edit `whisper-server.service`, Ollama, or anything under `/opt`.
- Do not `ollama pull`, and do not load any Ollama model other than `KERSTIN_OLLAMA_MODEL`.
- Do not write audio or transcripts to disk. The smoke test builds its utterance in memory.
- Stop the Kerstin server you started (`make run`) when you're done.

## Spec
1. **Setup.** Run `make setup` and `make voice`. If `piper-tts` fails to install on aarch64, record the exact error and what fixed it (version pin, etc.) in the report. You may change only the `piper` extra in `backend/pyproject.toml`. Note the installed version (`pip show piper-tts`).
2. **New STT backend `WhisperCppSTT`** in `backend/kerstin/stt.py`, behind the existing `STT` Protocol. Leave `HttpSTT` unchanged.
   - Constructor: `WhisperCppSTT(s: Settings, client: httpx.AsyncClient | None = None)`. The optional client is there so tests can inject one.
   - `POST {stt_url}{stt_inference_path}` as multipart: `file` = 16 kHz mono WAV (`pcm16_to_wav`), `language` = `s.stt_language`, `response_format` = `json`, `temperature` = `0.0`.
   - Response `{"text": "..."}` → return the stripped text. Non-2xx → raise (`raise_for_status`).
   - Config (`config.py`): add `"whispercpp"` to the `stt_backend` Literal and add `stt_inference_path: str = "/inference"`. In `make_stt`, map `"whispercpp"` to `WhisperCppSTT`.
3. **Unit tests** `backend/tests/test_stt.py` using `httpx.MockTransport` (no network):
   - the request goes to `/inference`; the multipart body contains `language` = `de` and a WAV file (`RIFF` header);
   - the response text is stripped;
   - HTTP 500 → `transcribe` raises `httpx.HTTPStatusError`;
   - `make_stt` returns `WhisperCppSTT` for `stt_backend="whispercpp"`.
4. **Config files.**
   - `.env.example`: default to `KERSTIN_STT_BACKEND=whispercpp`, `KERSTIN_STT_URL=http://127.0.0.1:8768`, with a comment explaining the `http` / `local` alternatives.
   - Set the same two values in your local `.env` (it is gitignored, not committed).
   - `scripts/check_env.sh`: for `whispercpp`, check that `GET $STT/` returns 200 (GET only, never POST). Keep the existing `http` branch unchanged.
5. **`scripts/smoke_test.py`** + `make smoke` target. Use only what the venv already has: `websockets` (comes with `uvicorn[standard]`), `httpx`, `numpy`, `piper`. No new dependencies.
   - CLI: `--url` (default `ws://127.0.0.1:8770/ws`), `--scenario` (default: server default), `--turns` (default 2).
   - Print `GET /health` first.
   - **Thermal guard:** read `nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits` before each turn and at the end, and print it. If the GPU is at or above 80 °C, abort with exit code 3. If `nvidia-smi` is missing, print a warning and continue.
   - Build the utterance in memory: synthesize `"Am Wochenende war ich mit Freunden am See, und das Wetter war fantastisch."` with Piper (voice from settings), resample from the voice's sample rate to 16 kHz with numpy linear interpolation, and convert to Int16 LE PCM bytes. Pad with 300 ms of silence at each end.
   - Send `start`, then wait for `reply_done` for turn 0 (the opener). For each turn n = 1..`--turns`: send the PCM as one binary frame, then wait for `transcript`, at least one `reply_text`, at least one binary frame whose 4-byte header equals n, then `reply_done` and `metrics` for turn n.
   - Timeouts: 60 s for turn 1 (may include cold model load), 20 s for each later turn.
   - Print every received message on one line, with ms since the utterance was sent. For binary frames, print the turn id and size only.
   - **Fail** (exit 1, with the reason) if: a turn times out; an `error` message arrives; the transcript contains neither `Wochenende` nor `See` (case-insensitive; this catches the English-default problem); or any `reply_text` contains `<think` or `</think>`.
   - End with a summary table per turn: `stt_ms`, `llm_first_token_ms`, `first_audio_ms` (server), client-measured first audio ms, `total_ms`, and GPU °C before/after.
   - `Makefile`: add `smoke` (`$(PY) scripts/smoke_test.py`) to the targets and `.PHONY`, and change `lint` to `ruff check backend scripts`.
6. **Run it.** `make check` → `make run` (in the background) → `make smoke` → `ollama ps` → stop the server. Paste the output of `make check`, `make smoke` and `ollama ps` into the report.
7. **Don't** run benchmarks or model comparisons (that's T002).

## Files allowed to change
- `backend/kerstin/stt.py` (add `WhisperCppSTT` + `make_stt` branch only)
- `backend/kerstin/config.py` (Literal + `stt_inference_path` only)
- `backend/tests/test_stt.py` (new)
- `scripts/smoke_test.py` (new)
- `scripts/check_env.sh` (whispercpp branch only)
- `Makefile` (`smoke` target, `lint` path)
- `.env.example`
- `backend/pyproject.toml` (`piper` extra only, only if step 1 needs it)
- this task file (Worker report section only)

## Out of scope
Persona/prompt changes, frontend changes, session/protocol changes, model comparisons, STT hallucination filtering (T013), browser testing (Sameer does that after merge).

## Acceptance criteria
- [ ] `make test` and `make lint` pass; `test_stt.py` contains the 4 tests from spec step 3
- [ ] `make check` shows Ollama + model OK and Whisper at `:8768` OK
- [ ] `make smoke` exits 0 against a running Kerstin on the GB10, with 2 turns; the transcript contains "Wochenende" or "See"; no `<think>` text
- [ ] Turn 2 (warm) server `first_audio_ms` is reported. Target < 1500 ms; if it's over, the report says which stage is slow (no fix needed in this task)
- [ ] GPU < 80 °C before and after every turn (from the smoke-test output)
- [ ] Worker report lists: piper-tts version, Ollama version, model + `ollama ps` size/processor, whisper.cpp language confirmed `de`, cold vs warm latencies
- [ ] `git diff main --stat` shows only allowed files; no audio files in the working tree

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
