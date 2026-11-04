# Status

_Last updated: 2026-11-04 (T000 scaffold)_

## Works (verified in a dev sandbox, not on the GB10)
- Unit tests: sentence splitter (abbreviations, ordinals, quotes) and session pipeline with fake STT/LLM/TTS, including barge-in cancel and feedback. `make test` → 10 passed.
- App starts; `/health`, `/api/scenarios`, `/`, static files served; WebSocket `start` → session + opener text.

## Not yet verified (T001 will check these on the GB10)
- Real Ollama streaming with `qwen3:30b-a3b` and `think: false` (older Ollama versions may ignore `think`; `strip_think` removes leftover `<think>` blocks either way).
- Sameer's Whisper server: does it expose OpenAI-compatible `POST /v1/audio/transcriptions`? If it is whisper.cpp's server (`/inference`) or something else, `HttpSTT` needs a small variant.
- `piper-tts` on aarch64: install + `PiperVoice.load` + `synthesize_wav`. Code handles both the new (`synthesize_wav`) and old (`synthesize`) APIs.
- `LocalSTT` (faster-whisper): CTranslate2 PyPI wheels for aarch64 may be CPU-only; CUDA may need a source build. Not on the default path.
- vad-web 0.0.22 asset paths from jsdelivr (`baseAssetPath`, `onnxWASMBasePath`).
- Real latency numbers.

## Known limitations
- Feedback is shown as raw Markdown text.
- No echo cancellation beyond the browser's default — use headphones.
- Single-user, no auth, binds to 127.0.0.1.
