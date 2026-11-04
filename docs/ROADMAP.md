# Roadmap

The lead (Claude Code) ticks items and writes task files. IDs are stable — refer to them in branches and commits.

## Phase 0 — Scaffold ✅
- [x] T000 Scaffold: FastAPI + WebSocket, HTTP/local STT, Ollama streaming, Piper TTS, sentence splitter, browser VAD client, persona + 5 scenarios, feedback, unit tests with fakes.

## Phase 1 — Bring-up on the GB10 (make it work end-to-end)
- [x] T001 **Bring-up & smoke test** on the GB10: `WhisperCppSTT`, `make smoke` (2026-11-04).
- [ ] T002 **Latency baseline**: `make bench`, p50/p90 per stage plus the estimated true end-of-speech → audio time (VAD tail included), Piper `high` vs `medium`. Model fixed at `qwen3:14b` (D009). Task file: `docs/tasks/T002-latency-baseline.md`.
- [ ] T003 **Vendor frontend assets** (vad-web, onnxruntime-web, Silero model) into `frontend/vendor/` so it works offline and isn't CDN-dependent.
- [ ] T005 **Model warm-up on session start**: fire a tiny Ollama request when `start` arrives (in parallel with the opener) so the first learner turn doesn't pay the ~7 s cold load. Respect `keep_alive`.
- [ ] T004 **Render feedback Markdown** in the browser (small vendored renderer, sanitized).

## Phase 2 — Conversation quality
- [ ] T010 **Persona tuning**: evaluate replies across scenarios for B2 level, length, peer tone, no mid-conversation correction; adjust `persona.md`. Include 3 before/after samples.
- [ ] T011 **Separate feedback model** setting (`KERSTIN_FEEDBACK_MODEL`), allow a larger model for the report.
- [ ] T012 **Kokoro German TTS** via `HttpTTS` (or in-process ONNX); A/B against Piper for naturalness and latency.
- [ ] T013 **STT robustness**: German initial prompt / hotwords, handle hallucinated "Untertitel der Amara.org-Community"-style outputs on silence; drop or re-ask.
- [ ] T014 **Echo handling**: document headphones; optionally pause VAD while Kerstin speaks with a "push-to-interrupt" mode.

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
