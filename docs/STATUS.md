# Status

_Last updated: 2026-11-04 (T001 bring-up merged)_

## Works on the GB10 (T001, 2026-11-04)
- End-to-end headless: `make smoke` passes. German utterance → whisper.cpp (`:8768`, `language=de`) → Ollama → Piper → WAV over `/ws`.
- Versions: Python 3.12.3 (aarch64), piper-tts 1.8.0 (installs cleanly), Ollama 0.34.2, `think: false` works (no `<think>` text seen).
- Model tested so far: **`qwen3:14b`** (local `.env`; 9.8 GB, 100% GPU). The committed default `qwen3:30b-a3b` is **not pulled and not tested yet**.
- Warm latency (server-side, from receiving the utterance): first audio 1.2–2.2 s. STT 0.36–0.70 s (varies with load on the shared Whisper server), LLM first token +0.1 s, first sentence complete ≈0.7 s later, Piper ≈0.65 s for the first sentence. Cold first turn: ≈8.8 s (model load).
- GPU stayed at 47–59 °C during smoke runs.

## Works (verified in a dev sandbox)
- Unit tests: sentence splitter (abbreviations, ordinals, quotes) and session pipeline with fake STT/LLM/TTS, including barge-in cancel and feedback. `make test` → 14 passed (includes the T001 `WhisperCppSTT` tests).
- App starts; `/health`, `/api/scenarios`, `/`, static files served; WebSocket `start` → session + opener text.

## Not yet verified
- `qwen3:30b-a3b` (default model) is untested.
- The real browser path: mic → vad-web (CDN) → reply audio via the SSH tunnel. Sameer tests this by hand.
- `LocalSTT` (faster-whisper): CTranslate2 PyPI wheels for aarch64 may be CPU-only; CUDA may need a source build. Not on the default path.
- vad-web 0.0.22 asset paths from jsdelivr (`baseAssetPath`, `onnxWASMBasePath`).
- True end-of-speech latency, including the browser VAD tail (T002).

## Known limitations
- **Latency over target** once the VAD tail is counted (≈1.8–2.9 s vs < 1.5 s).
- `qwen3:14b` produced a German grammar error ("haben sie auch geregnet"). Model choice is still open (T002).
- First turn after the model has been idle/unloaded takes ≈9 s (T005).
- Short utterances (< 0.35 s) get no server reply at all, so the UI stays on "du sprichst …".
- Feedback is shown as raw Markdown text.
- No echo cancellation beyond the browser's default — use headphones.
- Single-user, no auth, binds to 127.0.0.1.
