# Status

_Last updated: 2026-11-04 (T032 HTTPS on the LAN merged)_

## Works on the GB10 (T001, 2026-11-04)
- End-to-end headless: `make smoke` passes. German utterance → whisper.cpp (`:8768`, `language=de`) → Ollama → Piper → WAV over `/ws`.
- Versions: Python 3.12.3 (aarch64), piper-tts 1.8.0 (installs cleanly), Ollama 0.34.2, `think: false` works (no `<think>` text seen).
- Model: **`qwen3:14b`**, the default since D009 (9.8 GB, 100% GPU).
- Warm latency (server-side, from receiving the utterance): first audio 1.2–2.2 s. STT 0.36–0.70 s (varies with load on the shared Whisper server), LLM first token +0.1 s, first sentence complete ≈0.7 s later, Piper ≈0.65 s for the first sentence. Cold first turn: ≈8.8 s (model load).
- GPU stayed at 47–59 °C during smoke runs.

- Browser path works (Sameer, 2026-11-04): mic → vad-web (CDN) → reply audio over the SSH tunnel.

- HTTPS on the LAN (T032): Uvicorn TLS with a local CA (`make certs`). Verified with curl and a `wss://` smoke test from the GB10; Sameer's check from the Mac is still pending. Names in the cert: `promaxgb10-6116.fritz.box` (recommended), `.local`, `192.168.178.55`, `localhost`.
- mDNS caveat: avahi advertises the Docker bridge (`172.30.0.1`) for `promaxgb10-6116.local`, so prefer the `.fritz.box` name or the IP.

## Works (verified in a dev sandbox)
- Unit tests: sentence splitter (abbreviations, ordinals, quotes) and session pipeline with fake STT/LLM/TTS, including barge-in cancel and feedback. `make test` → 21 passed (STT and TLS tests included).
- App starts; `/health`, `/api/scenarios`, `/`, static files served; WebSocket `start` → session + opener text.

## Not yet verified
- `LocalSTT` (faster-whisper): CTranslate2 PyPI wheels for aarch64 may be CPU-only; CUDA may need a source build. Not on the default path.
- True end-of-speech latency, including the browser VAD tail (T002).

## Known limitations
- **Latency over target** once the VAD tail is counted (≈1.8–2.9 s vs < 1.5 s).
- `qwen3:14b` produced a German grammar error ("haben sie auch geregnet"). Watch for this in T010 (persona tuning).
- First turn after the model has been idle/unloaded takes ≈9 s (T005).
- Short utterances (< 0.35 s) get no server reply at all, so the UI stays on "du sprichst …".
- Feedback is shown as raw Markdown text.
- No echo cancellation beyond the browser's default — use headphones.
- Single-user, no auth. Default bind is 127.0.0.1; with `KERSTIN_HOST=0.0.0.0` anyone on the LAN or NordVPN Meshnet can use it (D010, auth comes with T040).
