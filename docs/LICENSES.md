# Component licenses

Kerstin may become a public, paid service. Every shipped component must allow commercial use. **Verify each entry against the upstream license before going public (T043)** — this table is a starting point, not legal advice.

| Component | Role | License (as understood) | Commercial OK? | Notes |
|---|---|---|---|---|
| FastAPI, Uvicorn, httpx, pydantic | server | MIT / BSD | ✅ | |
| OpenAI Whisper weights | STT | MIT | ✅ | |
| faster-whisper / CTranslate2 | STT (optional) | MIT | ✅ | |
| Qwen3 (Ollama) | LLM | Apache 2.0 | ✅ | default |
| Mistral Small 3.x | LLM alt | Apache 2.0 | ✅ | |
| Gemma 4 (`gemma4:26b`) | LLM (default, D015) | Apache 2.0 (per Ollama model card) | ✅ (verify upstream) | earlier Gemma 3 used the Gemma Terms of Use — confirm Gemma 4 is plain Apache 2.0 before going public |
| Gemma 4 31B (`gemma4:31b`) | LLM (feedback eval only) | Apache 2.0 (per Ollama model card) | ✅ (verify upstream) | 19 GB dense; eval only, verify license upstream in T043 |
| Qwen3 14B | LLM alt | Apache 2.0 | ✅ | previous default (D009) |
| Ollama | LLM runtime | MIT | ✅ | |
| piper-tts (piper1-gpl) | TTS engine | GPL-3.0 | ⚠️ | OK for a hosted service; distribution of a bundled app has GPL obligations. Original rhasspy/piper was MIT. |
| Piper voices `de_DE-thorsten-medium` (default), `-high` | TTS voice | Thorsten dataset CC0 (check voice card) | ✅ (verify) | |
| kokoro (semidark fork) | TTS engine | Apache-2.0 | ✅ | pinned `b96fef95e6a746495f92443fac7c688f90fc57fc`; fork of hexgrad/kokoro for German |
| misaki (semidark fork) | G2P | Apache-2.0 | ✅ | pinned `6d252a2e02f3b030f22f56686f1a73786c16ffc8`; uses espeak-ng |
| espeak-ng | G2P runtime | GPL-3.0 | ⚠️ | same situation as Piper; system library, no bundling decided |
| torch | TTS runtime | BSD-3-Clause | ✅ | CUDA wheel 2.9.1+cu130 in `.venv-kokoro` only |
| Kokoro German Thorsten (`Thorsten-Voice/Kokoro`) | TTS voice | Apache-2.0; Thorsten-Voice dataset CC0 | ✅ | weights and dataset card saved under `voices/kokoro/thorsten/` |
| Kokoro German Kerstin (`cryptomilk/kokoro-german-kerstin`) | TTS voice | Apache-2.0; Kerstin 1.0 dataset CC0-1.0 | ✅ | weights + LICENSE saved under `voices/kokoro/kerstin/` |
| Kokoro German Victoria (`kikiri-tts/kikiri-german-victoria`) | TTS voice | Apache-2.0; synthetic Victoria voice | ✅ (verify synthetic-data terms before public use) | weights card saved under `voices/kokoro/victoria/` |
| Coqui XTTS v2 | TTS | Coqui Public Model License | ❌ | non-commercial — do not use in default path |
| @ricky0123/vad-web | browser VAD | ISC | ✅ | |
| Silero VAD model | VAD | MIT | ✅ | |
| onnxruntime-web | browser runtime | MIT | ✅ | |

The browser assets for `@ricky0123/vad-web`, the Silero VAD model and `onnxruntime-web` are downloaded by `make vendor` into `frontend/vendor/` (gitignored) together with each package's `LICENSE` file.
