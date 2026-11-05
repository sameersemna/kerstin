# Roadmap

The lead (Claude Code) ticks items and writes task files. IDs are stable — refer to them in branches and commits.

## Phase 0 — Scaffold ✅
- [x] T000 Scaffold: FastAPI + WebSocket, HTTP/local STT, Ollama streaming, Piper TTS, sentence splitter, browser VAD client, persona + 5 scenarios, feedback, unit tests with fakes.

## Phase 1 — Bring-up on the GB10 (make it work end-to-end)
- [x] T001 **Bring-up & smoke test** on the GB10: `WhisperCppSTT`, `make smoke` (2026-11-04).
- [x] T002 **Latency baseline**: `make bench` + `first_sentence_ms`/`tts_first_ms` metrics (2026-11-04). Results in STATUS.
- [ ] T003 **Vendor frontend assets** (vad-web, onnxruntime-web, Silero model) into `frontend/vendor/` so it works offline and isn't CDN-dependent.
- [x] T005 **Warm-up + random seed** (2026-11-05): cold first turn 8.8 s → 1.4 s; replies vary across sessions.
- [x] T006 **Speak the first clause early** (2026-11-05): paired median −379 ms; fires in ~30–60 % of turns.
- [ ] T004 **Render feedback Markdown** in the browser (small vendored renderer, sanitized).

## Phase 2 — Conversation quality
- [x] T010 **Persona eval + tuning** (2026-11-05): `make persona-eval`, `reply_checks.py`, revised `persona.md` (length fixed; grammar not, see D014).
- [x] T015 **Model comparison for German correctness** (2026-11-05): gemma4:26b 5 % vs qwen3:14b 18 % errors → default gemma4:26b (D015).
- [ ] T011 **Separate feedback model** setting (`KERSTIN_FEEDBACK_MODEL`), allow a larger model for the report.
- [ ] T012 **Kokoro German TTS** via `HttpTTS` (or in-process ONNX); A/B against Piper for naturalness and latency.
- [x] T013 **STT robustness** (2026-11-05): energy gate (−55 dBFS), hallucination filter, `stt_empty` reasons, `audio_dbfs` in the UI.
- [x] T014 **Echo handling**: speaker mode (mic paused while Kerstin speaks, default), headphone mode (voice barge-in), interrupt button/space bar, server echo filter. Task file: `docs/tasks/T014-echo-handling.md`.

## Phase 3 — Learning features
- [ ] T020 **Mistake log** (opt-in, local SQLite): store feedback items per session; Kerstin steers future conversations toward weak structures.
- [ ] T021 **Exam mode** (telc / Goethe B2 mündlich formats): timed parts, Vortrag + Diskussion + Planung, rubric-based scoring.
- [ ] T022 **Hint button**: learner asks "Wie sagt man …?" in English → Kerstin answers in German, short.
- [ ] T023 **Session history page** (transcripts + feedback, local only).

## Phase 4 — Ops on the shared GB10
- [ ] T030 **Thermal guard**: poll `nvidia-smi`; above 80 °C, reject new sessions / switch to smaller model; never cap clocks machine-wide.
- [ ] T031 **systemd user service** + log rotation; start on boot optional.
- [x] T032 **HTTPS on LAN** (Uvicorn TLS + local CA, D010): `make certs`, `KERSTIN_TLS_*` (2026-11-04).

## Phase 5 — Going public (only after Sameer decides)
- [ ] T040 Auth + per-user limits; multi-session concurrency test.
- [ ] T041 GDPR: privacy policy, Impressum, AI disclosure (EU AI Act Art. 50), no audio retention.
- [ ] T042 Cloud GPU deployment path + cost per conversation minute.
- [ ] T043 License audit of every shipped component (`docs/LICENSES.md` → all green).
