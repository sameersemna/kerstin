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
  - `backend/kerstin/stt.py` — added `WhisperCppSTT` (multipart `POST {stt_url}{stt_inference_path}`, sends `language`, `response_format=json`, `temperature=0.0`; returns stripped `text`; accepts an injected `httpx.AsyncClient`) and the `make_stt` branch. `HttpSTT` untouched.
  - `backend/kerstin/config.py` — `"whispercpp"` added to the `stt_backend` Literal and `stt_inference_path: str = "/inference"`.
  - `backend/tests/test_stt.py` (new) — the 4 tests from spec step 3, using `httpx.MockTransport`.
  - `scripts/smoke_test.py` (new) — headless 2-turn E2E with in-memory Piper utterance, 16 kHz resampling, thermal guard (exit 3), transcript/think checks and per-turn summary.
  - `scripts/check_env.sh` — `whispercpp` branch checks `GET $STT/` (HTTP 200); `http` and `local` branches unchanged.
  - `Makefile` — added `smoke`, added it to `.PHONY`, lint now covers `backend scripts`.
  - `.env.example` — defaults to `KERSTIN_STT_BACKEND=whispercpp` / `KERSTIN_STT_URL=http://127.0.0.1:8768`, with the `http`/`local` alternatives documented.
  - `docs/tasks/T001-bringup.md` — Worker report only.
  - Local `.env` (gitignored, not committed): `KERSTIN_STT_BACKEND=whispercpp`, `KERSTIN_STT_URL=http://127.0.0.1:8768`, and `KERSTIN_OLLAMA_MODEL=qwen3:14b` (see deviation).
  - `backend/pyproject.toml` unchanged — `piper-tts` installed without changes.
- **How tested:**
  - `make setup` + `make voice`: venv on Python 3.12.3 (aarch64); `piper-tts 1.8.0` (GPL-3.0-or-later) installed cleanly, no version pin or workaround needed; default voice downloaded.
  - `make test` → `14 passed` in 0.27 s (4 new STT tests, no network/GPU).
  - `make lint` → `All checks passed!`
  - `make check`, `make run` (background) and `make smoke` (default `--turns 2`) against the real services; `make smoke` exited 0. The `make run` process was stopped afterwards.
  - Confirmed `WhisperCppSTT` sends `language=de` in the multipart body (unit test) and the live whisper.cpp transcript came back in German with “Wochenende” and “See”.
  - No audio/transcript files written to disk (`find` for audio extensions found none); the utterance is synthesized and resampled in memory.
- **Measurements (if any):**
  - piper-tts `1.8.0`; Ollama `0.34.2`; model `qwen3:14b`.
  - `ollama ps`: `qwen3:14b`, 9.8 GB, `100% GPU`, context 8192 (a second model, `bge-m3:latest`, was loaded by another consumer at the same time; Kerstin only used `qwen3:14b`).
  - whisper.cpp language: `de` (request field, asserted by test), live transcript: “Am Wochenende war ich mit Freunden am See und das Wetter war fantastisch.”
  - Cold vs warm (server metrics):

    | turn | stt_ms | llm_first_token_ms | first_audio_ms | total_ms |
    |---|---|---|---|---|
    | 1 (cold, includes model load) | 431 | 7400 | 8781 | 9720 |
    | 2 (warm) | 697 | 809 | 2169 | 3005 |

    Client-measured first audio: 8787 ms (turn 1), 2175 ms (turn 2). GPU: 51 °C before turn 1, 58 °C after; 58 °C before turn 2, 59 °C after; 55 °C at end. All well below 80 °C.
  - Warm turn 2 `first_audio_ms` is 2169 ms, above the 1500 ms target. Stage breakdown: STT ≈ 0.70 s (shared whisper.cpp server, single request at a time), then ≈ 0.82 s from end of STT to the first complete sentence (`llm_first_token_ms=809`; the first token itself follows STT by ≈ 0.11 s), then ≈ 0.65 s Piper synthesis before the first audio frame. No fix attempted (out of scope for T001).
- **Deviations from spec / extra files touched:**
  - **Model:** the prerequisite `qwen3:30b-a3b` was not pulled when the task started (`ollama list` did not contain it; `make check` reported it missing). I did not pull it. Per Sameer’s explicit instruction, the local (gitignored) `.env` was set to the already-pulled `qwen3:14b` for the smoke run. `.env.example` and every committed default still say `qwen3:30b-a3b`. The measurements above are therefore for `qwen3:14b`, not the intended default.
  - The thermal guard reads the GPU before **and after** each turn plus once at the end (slightly more than the “before each turn and at the end” minimum), so the summary can show before/after.
  - Opener (`turn 0`) messages are timestamped relative to `start`, since no learner utterance exists for that turn.
  - No other files touched.
- **New dependencies (+license):** None added. `websockets 17.4` (BSD-3-Clause), `numpy 2.5.4` (BSD-3-Clause) and `httpx 0.28.1` (BSD-3-Clause) were already in the venv; `piper-tts 1.8.0` is the pre-existing optional extra (GPL-3.0-or-later).
- **Open questions:**
  - Should the warm-turn 2.17 s first-audio (STT/TTS dominated on this shared host) be picked up by T002? No fix was attempted here.
  - The intended `qwen3:30b-a3b` was never exercised; the T001 acceptance data should be re-run once that model is pulled if the MoE latency matters.

### Outputs

`make check`:

```text
$ make check
bash scripts/check_env.sh
Ollama (http://127.0.0.1:11434)
  [ok]   reachable
  [ok]   model qwen3:14b present
STT (whispercpp)
  [ok]   http://127.0.0.1:8768/ answers
TTS (piper)
  [ok]   voice voices/de_DE-thorsten-high.onnx
GPU
  [ok]   GPU at 53 °C
         2682627, /usr/libexec/gnome-remote-desktop-daemon, 277 MiB
         3405863, /opt/whisper/whisper-server, 3930 MiB
         1059689, /usr/libexec/gnome-remote-desktop-daemon, 176 MiB
         4165662, /usr/local/lib/ollama/llama-server, 9665 MiB
         64461, /usr/local/lib/ollama/llama-server, 870 MiB
```

`make smoke`:

```text
$ make smoke
.venv/bin/python scripts/smoke_test.py
GET http://127.0.0.1:8770/health -> 200
{"version":"0.1.0","ollama":{"ok":true,"model_available":true},"model":"qwen3:14b","stt_backend":"whispercpp","tts_backend":"piper"}
Synthesizing utterance with Piper voice de_DE-thorsten-high.onnx ...
Utterance: 4.32 s, 138086 bytes PCM
Sending {"type": "start"}
[     0 ms] {"type": "session", "scenario": "freies_gespraech", "title": "Freies Gespräch"}
[     0 ms] {"type": "reply_text", "turn": 0, "text": "Hey, schön, dass es heute klappt! Ich habe gerade einen Flat White bestellt. Wie war deine Woche bisher?"}
[   955 ms] binary turn=0 size=252464
[   955 ms] {"type": "reply_done", "turn": 0}
Opener complete
GPU before turn 1: 51 °C
[     4 ms] {"type": "status", "state": "transcribing", "turn": 1}
[   436 ms] {"type": "transcript", "turn": 1, "text": "Am Wochenende war ich mit Freunden am See und das Wetter\n war fantastisch."}
[   436 ms] {"type": "status", "state": "thinking", "turn": 1}
[  8182 ms] {"type": "reply_text", "turn": 1, "text": "Schön, dass du mit Freunden am See warst!"}
[  8787 ms] binary turn=1 size=95280
[  8787 ms] {"type": "reply_text", "turn": 1, "text": "Wie war das Wetter genau?"}
[  9185 ms] binary turn=1 size=54320
[  9323 ms] {"type": "reply_text", "turn": 1, "text": "War es sonnig oder haben sie auch geregnet?"}
[  9726 ms] binary turn=1 size=95280
[  9726 ms] {"type": "reply_done", "turn": 1}
[  9726 ms] {"type": "metrics", "turn": 1, "audio_s": 4.32, "stt_ms": 431, "llm_first_token_ms": 7400, "first_audio_ms": 8781, "total_ms": 9720, "sentences": 3}
GPU after turn 1: 58 °C
Turn 1 complete
GPU before turn 2: 58 °C
[     4 ms] {"type": "status", "state": "transcribing", "turn": 2}
[   701 ms] {"type": "transcript", "turn": 2, "text": "Am Wochenende war ich mit Freunden am See und das Wetter\n war fantastisch."}
[   702 ms] {"type": "status", "state": "thinking", "turn": 2}
[  1524 ms] {"type": "reply_text", "turn": 2, "text": "Schön, dass du mit Freunden am See warst!"}
[  2175 ms] binary turn=2 size=88112
[  2175 ms] {"type": "reply_text", "turn": 2, "text": "Wie war das Wetter genau?"}
[  2486 ms] binary turn=2 size=57392
[  2649 ms] {"type": "reply_text", "turn": 2, "text": "War es sonnig oder haben sie auch geregnet?"}
[  3010 ms] binary turn=2 size=106032
[  3010 ms] {"type": "reply_done", "turn": 2}
[  3010 ms] {"type": "metrics", "turn": 2, "audio_s": 4.32, "stt_ms": 697, "llm_first_token_ms": 809, "first_audio_ms": 2169, "total_ms": 3005, "sentences": 3}
GPU after turn 2: 59 °C
Turn 2 complete
GPU at end: 55 °C

Summary
turn   stt_ms  llm_1st_ms  srv_audio_ms  cli_audio_ms  total_ms  gpu_before  gpu_after
--------------------------------------------------------------------------------------
   1      431        7400          8781          8787      9720       51 °C      58 °C
   2      697         809          2169          2175      3005       58 °C      59 °C
```

`ollama ps`:

```text
$ ollama ps
NAME             ID              SIZE      PROCESSOR    CONTEXT    UNTIL
qwen3:14b        bdbd181c33f2    9.8 GB    100% GPU     8192       9 minutes from now
bge-m3:latest    790764642607    664 MB    100% GPU     8192       9 minutes from now
```

## Review (Claude Code fills this in)
- **Verdict:** accept (2026-11-04)
- **Notes:**
  - Diff limited to allowed files. `make test` (14 passed) and `make lint` pass on review. No audio files in the tree.
  - Lead re-ran `make smoke --turns 3` with `qwen3:14b` already warm: server `first_audio_ms` was 1279 / 1220 / 1593 ms, STT 356–431 ms, GPU 48–58 °C. Kilo's run (2169 ms, STT 697 ms) was the same pipeline; the spread is consistent with the shared whisper.cpp server and run-to-run variance.
  - All numbers start when the server receives the audio. The browser's VAD silence tail (≈0.5–0.8 s) comes on top, so the real end-of-speech → audio time is ≈1.8–2.9 s. Handed to T002.
  - Cold first turn: 7.4 s to first token (model load). Follow-up: T005 warm-up.
  - Persona issue seen with `qwen3:14b`: "War es sonnig oder **haben sie** auch geregnet?" (should be "hat es"). This is a grammar error, which breaks the persona contract. The model also asked about the weather right after being told it was fantastic. Input for the T002 model comparison and T010.
  - Nit (not blocking): `smoke_test.py` imports `SynthesisConfig` at module level, so its `ImportError` fallback can never trigger. Harmless with piper-tts 1.8.0.
