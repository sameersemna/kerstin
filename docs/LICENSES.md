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
| Qwen3 14B | LLM alt | Apache 2.0 | ✅ | previous default (D009) |
| Ollama | LLM runtime | MIT | ✅ | |
| piper-tts (piper1-gpl) | TTS engine | GPL-3.0 | ⚠️ | OK for a hosted service; distribution of a bundled app has GPL obligations. Original rhasspy/piper was MIT. |
| Piper voices `de_DE-thorsten-medium` (default), `-high` | TTS voice | Thorsten dataset CC0 (check voice card) | ✅ (verify) | |
| Kokoro-82M German ports | TTS alt | Apache 2.0 (check each fine-tune) | ✅ (verify) | |
| Coqui XTTS v2 | TTS | Coqui Public Model License | ❌ | non-commercial — do not use in default path |
| @ricky0123/vad-web | browser VAD | ISC | ✅ | |
| Silero VAD model | VAD | MIT | ✅ | |
| onnxruntime-web | browser runtime | MIT | ✅ | |
