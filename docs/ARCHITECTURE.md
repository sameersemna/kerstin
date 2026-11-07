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
| Text-to-speech | Server | `backend/kerstin/tts.py` | Kokoro `kokoro-kerstin` (default) + Piper fallback; optional sidecar on 8880; per-session voice |
| Persona & scenarios | Server | `backend/prompts/` | `persona.md`, `scenarios.json`, `feedback.md` |

## Turn flow

```
learner speaks ─▶ draft after ≈192 ms pause (KDR1, early STT only)
  └▶ Session.handle_draft: STT runs while the rest of the VAD tail elapses
       └▶ latest draft only; resume speech invalidates it in the browser

VAD detects end (≈0.5–0.8 s silence) ─▶ commit? + Int16 PCM over /ws
  └▶ Session.handle_audio: cancel running turn (barge-in), new turn_id
       └▶ gates on final audio ─▶ committed draft transcript or fresh STT
            └▶ transcript sent to client, appended to history
                 └▶ LLM stream ─▶ SentenceSplitter ─▶ queue
                        └▶ consumer: reply_text ─▶ TTS ─▶ [turn_id|WAV] to client
                 (producer and consumer run concurrently → first sentence plays while LLM still writes)
  └▶ metrics (stt_early, stt_wait_ms, llm_first_token_ms, first_audio_ms, total_ms)
```

Barge-in: if the learner starts speaking while audio plays, the browser stops playback and sends `interrupt`; the server cancels the turn task. Binary audio frames carry a 4-byte turn id so the client drops stale audio. Only sentences that were actually synthesized go into history.

End of session: `end` → `Session.feedback()` runs one non-streaming LLM call with `prompts/feedback.md` over the transcript, returns Markdown.

## Latency budget (target: < 1.5 s end-of-speech → first audio)

| Stage | Budget | Knob |
|---|---|---|
| VAD end-of-turn silence | 0.768 s | `redemptionFrames=8` in `app.js` (D012: do not shorten) |
| STT wait after the final binary | ≈0 s (draft) / 0.2–0.5 s fallback | early STT (D013); shared Whisper model/beam size |
| LLM first sentence | 0.3–0.8 s | MoE model, `num_predict`, short system prompt, keep model warm |
| TTS first sentence | 0.1–0.2 s | Kokoro `kokoro-kerstin`; Piper fallback |

These are estimates to be verified by T002/T018 (latency baseline). The server sends real numbers in the `metrics` message per turn.

### Early STT (T007, D013)
The 768 ms VAD tail stays fixed. About 192 ms into a pause the browser sends a `KDR1` draft of the buffered utterance; the server starts STT without interrupting Kerstin. If the learner keeps talking, the browser invalidates the draft on the next speech frame. At `onSpeechEnd` it commits only the latest valid draft, then sends the final utterance. The server runs the normal gates on the final audio, reuses the committed draft transcript when the id matches, and falls back to a fresh STT if the draft is missing, stale, gated, or raised. Only STT runs early: there is no speculative LLM or TTS. `metrics.stt_early` / `metrics.stt_wait_ms` show the win; `drafts_sent`, `drafts_committed` and `drafts_wasted_stt` are logged at INFO on `end` (counts only).

GB10 note: large unified memory but moderate memory bandwidth — dense 27B+ models generate slowly. Prefer MoE (`qwen3:30b-a3b`) or ≤ 14B dense models for the conversation; a larger model is fine for the end-of-session feedback if latency there doesn't matter (future: separate `feedback_model` setting).

## Concurrency & resources
- One `Session` per WebSocket. Default deployment is single-user on the GB10.
- STT and TTS clients are shared across sessions. Piper runs on CPU (Grace cores) in a thread.
- Ollama `keep_alive` (default 10 m) unloads the model when idle so the shared GPU is released.
- Deployment: `make service-install` runs Kerstin as a systemd user service with journald logs and rate-limited restarts.

## Things deliberately not done yet
Authentication, multi-user, HTTPS, persistence, markdown rendering of feedback, server-side VAD, streaming TTS within a sentence. See `docs/ROADMAP.md`.
