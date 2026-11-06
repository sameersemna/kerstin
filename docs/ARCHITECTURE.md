# Architecture

## Components

| Layer | Where | File | Default engine |
|---|---|---|---|
| Mic + turn detection | Browser | `frontend/app.js` | Silero VAD via vendored `@ricky0123/vad-web` |
| Transport | Browser ↔ server | `/ws`, `docs/PROTOCOL.md` | WebSocket, binary PCM up, binary WAV down |
| Session / turn orchestration | Server | `backend/kerstin/session.py` | — |
| Speech-to-text | Server | `backend/kerstin/stt.py` | HTTP to existing Whisper server (`HttpSTT`) or `LocalSTT` (faster-whisper) |
| LLM | Server | `backend/kerstin/llm.py` | Ollama `/api/chat`, streaming, `think: false` |
| Sentence splitting | Server | `backend/kerstin/text.py` | German-aware (abbreviations, ordinals) |
| Text-to-speech | Server | `backend/kerstin/tts.py` | Piper `de_DE-thorsten-medium` (D011); `HttpTTS` for Kokoro-German |
| Persona & scenarios | Server | `backend/prompts/` | `persona.md`, `scenarios.json`, `feedback.md` |

## Turn flow

```
learner speaks ─▶ VAD detects end (≈0.5–0.8 s silence) ─▶ Int16 PCM over /ws
  └▶ Session.handle_audio: cancel running turn (barge-in), new turn_id
       └▶ STT ─▶ transcript sent to client, appended to history
            └▶ LLM stream ─▶ SentenceSplitter ─▶ queue
                                   └▶ consumer: reply_text ─▶ TTS ─▶ [turn_id|WAV] to client
            (producer and consumer run concurrently → first sentence plays while LLM still writes)
  └▶ metrics (stt_ms, llm_first_token_ms, first_audio_ms, total_ms)
```

Barge-in: if the learner starts speaking while audio plays, the browser stops playback and sends `interrupt`; the server cancels the turn task. Binary audio frames carry a 4-byte turn id so the client drops stale audio. Only sentences that were actually synthesized go into history.

End of session: `end` → `Session.feedback()` runs one non-streaming LLM call with `prompts/feedback.md` over the transcript, returns Markdown.

## Latency budget (target: < 1.5 s end-of-speech → first audio)

| Stage | Budget | Knob |
|---|---|---|
| VAD end-of-turn silence | 0.5–0.8 s | `redemptionFrames` in `app.js` |
| STT (large-v3 / turbo, ~3–8 s utterance) | 0.2–0.4 s | model size, beam size 1 |
| LLM first sentence | 0.3–0.8 s | MoE model, `num_predict`, short system prompt, keep model warm |
| TTS first sentence (Piper) | 0.1–0.2 s | voice quality tier |

These are estimates to be verified by T002 (latency baseline). The server sends real numbers in the `metrics` message per turn.

GB10 note: large unified memory but moderate memory bandwidth — dense 27B+ models generate slowly. Prefer MoE (`qwen3:30b-a3b`) or ≤ 14B dense models for the conversation; a larger model is fine for the end-of-session feedback if latency there doesn't matter (future: separate `feedback_model` setting).

## Concurrency & resources
- One `Session` per WebSocket. Default deployment is single-user on the GB10.
- STT and TTS clients are shared across sessions. Piper runs on CPU (Grace cores) in a thread.
- Ollama `keep_alive` (default 10 m) unloads the model when idle so the shared GPU is released.
- Deployment: `make service-install` runs Kerstin as a systemd user service with journald logs and rate-limited restarts.

## Things deliberately not done yet
Authentication, multi-user, HTTPS, persistence, markdown rendering of feedback, server-side VAD, streaming TTS within a sentence. See `docs/ROADMAP.md`.
