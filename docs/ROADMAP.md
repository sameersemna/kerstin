# Roadmap

The lead (Claude Code) ticks items and writes task files. IDs are stable — refer to them in branches and commits.

## Phase 0 — Scaffold ✅
- [x] T000 Scaffold: FastAPI + WebSocket, HTTP/local STT, Ollama streaming, Piper TTS, sentence splitter, browser VAD client, persona + 5 scenarios, feedback, unit tests with fakes.

## Phase 1 — Bring-up on the GB10 (make it work end-to-end)
- [x] T001 **Bring-up & smoke test** on the GB10: `WhisperCppSTT`, `make smoke` (2026-11-04).
- [x] T002 **Latency baseline**: `make bench` + `first_sentence_ms`/`tts_first_ms` metrics (2026-11-04). Results in STATUS.
- [x] T003 **Vendor frontend assets** (vad-web, onnxruntime-web, Silero model) into `frontend/vendor/` so it works offline and isn't CDN-dependent.
- [x] T005 **Warm-up + random seed** (2026-11-05): cold first turn 8.8 s → 1.4 s; replies vary across sessions.
- [x] T006 **Speak the first clause early** (2026-11-05): paired median −379 ms; fires in ~30–60 % of turns.
- [x] T004 **Render feedback Markdown** in the browser (D017: own DOM-only subset renderer, no library). Task file: `docs/tasks/T004-feedback-markdown.md`.

## Phase 2 — Conversation quality
- [x] T010 **Persona eval + tuning** (2026-11-05): `make persona-eval`, `reply_checks.py`, revised `persona.md` (length fixed; grammar not, see D014).
- [x] T015 **Model comparison for German correctness** (2026-11-05): gemma4:26b 5 % vs qwen3:14b 18 % errors → default gemma4:26b (D015).
- [x] T017 **Feedback language setting** (D008): English/German 💡 explanations, UI selector, `end.feedback_lang`. Task file: `docs/tasks/T017-feedback-language.md`.
- [x] T016 **Feedback quality eval** (after T017, both languages): planted-error fixtures, `make feedback-eval` (recall, false corrections, quote grounding), prompt revision if needed. Task file: `docs/tasks/T016-feedback-quality.md`.
- [x] T011 **Feedback model + temperature** (eviction-safe): `KERSTIN_FEEDBACK_TEMPERATURE`, optional `KERSTIN_FEEDBACK_MODEL` that never evicts other projects' models; eval gemma4:26b @0.8/0.3 vs gemma4:31b @0.3 (Sameer approved, already pulled). Task file: `docs/tasks/T011-feedback-model.md`.
- [x] T012 **Kokoro German TTS** via `HttpTTS` (or in-process ONNX); A/B against Piper for naturalness and latency.
- [x] T013 **STT robustness** (2026-11-05): energy gate (−55 dBFS), hallucination filter, `stt_empty` reasons, `audio_dbfs` in the UI.
- [x] T014 **Echo handling**: speaker mode (mic paused while Kerstin speaks, default), headphone mode (voice barge-in), interrupt button/space bar, server echo filter. Task file: `docs/tasks/T014-echo-handling.md`.

## Phase 3 — Learning features
- [x] T020 **Mistake log** (D020): opt-in, local SQLite, grammar categories only (no learner text), summary + delete in the UI. Task file: `docs/tasks/T020-mistake-log.md`.
- [x] T024 **Focus steering** (after T020): Kerstin creates natural chances to practise the top 1–2 weak categories; never corrects or mentions it. Task file: `docs/tasks/T024-focus-steering.md`.
- [x] T021 **Exam training engine** (D021): two presets (telc-style / Goethe-style B2 oral), part kinds prep / learner talk (collect) / Kerstin talk / dialog, original topic cards, `make exam-eval`. Task file: `docs/tasks/T021-exam-engine.md`.
- [x] T026 **Exam UI**: mode selector, part panel with task card, countdown, "Weiter"/"Fertig", auto-finish of the learner talk at time + 30 s.
- [x] T025 **Exam rubric scoring**: per-criterion estimate (task fulfilment, coherence, vocabulary, grammar; no pronunciation from text) + calibration eval on transcripts of known levels (ordering + stability); clearly labelled as an estimate.
- [x] T022 **Hint box** (D018): learner types "Wie sagt man …?" (English or German paraphrase) → short German answer with article/forms + example in a side panel; not spoken, not in history. Task file: `docs/tasks/T022-hint-button.md`.
- [x] T018 **Voice selection** (D024): default `kokoro-kerstin` (Kokoro sidecar on GPU, systemd unit, idle release), UI voice selector, Piper fallback.
- [ ] T023 **Session history page** (transcripts + feedback, local only).

## Phase 4 — Ops on the shared GB10
- [x] T030 **Thermal guard** (D016): before each GPU job read `nvidia-smi` temp (cached); ≥ 80 °C → pause sessions/turns/feedback until ≤ 74 °C, tell the learner; read-only, never cap clocks. Task file: `docs/tasks/T030-thermal-guard.md`.
- [x] T031 **systemd user service** + log rotation; start on boot optional.
- [x] T032 **HTTPS on LAN** (Uvicorn TLS + local CA, D010): `make certs`, `KERSTIN_TLS_*` (2026-11-04).

## Phase 5 — Going public (only after Sameer decides)
- [ ] T040 Auth + per-user limits; multi-session concurrency test.
- [ ] T041 GDPR: privacy policy, Impressum, AI disclosure (EU AI Act Art. 50), no audio retention.
- [ ] T042 Cloud GPU deployment path + cost per conversation minute.
- [ ] T043 License audit of every shipped component (`docs/LICENSES.md` → all green).
