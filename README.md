# Kerstin

A local, real-time German speaking partner at **B2 level**. You talk; Kerstin — a fellow B2 learner from Göteborg living in Berlin — talks back, asks follow-up questions and disagrees with you. She does **not** correct you mid-conversation; at the end you get a short feedback report.

Runs entirely on the Dell Pro Max GB10: **Whisper** (speech-to-text) → **Ollama** (LLM) → **Piper** (German TTS), with a browser client.

```
Browser (mic + Silero VAD) ──PCM──▶ FastAPI /ws ──▶ Whisper ──▶ Ollama (stream) ──▶ sentence splitter ──▶ Piper ──WAV──▶ Browser
```

## Quickstart (on the GB10)

```bash
make setup          # venv + deps, creates .env from .env.example
make voice          # download de_DE-thorsten-high Piper voice
ollama pull qwen3:30b-a3b
# edit .env: point KERSTIN_STT_URL at your Whisper server
make check          # Ollama, STT, voice, GPU temperature
make run            # http://127.0.0.1:8770
make test           # unit tests, no GPU needed
```

## Using it from the Mac

The browser only allows the microphone on `localhost` or HTTPS. Kerstin binds to `127.0.0.1` on the GB10, so use an SSH tunnel:

```bash
ssh -N -L 8770:127.0.0.1:8770 promaxgb10-6116
# then open http://localhost:8770 on the Mac
```

Use headphones — otherwise Kerstin's voice can trigger the mic (barge-in).

## Configuration

All settings are `KERSTIN_*` environment variables (see `.env.example`, defined in `backend/kerstin/config.py`). Most important:

| Setting | Default | Notes |
|---|---|---|
| `KERSTIN_OLLAMA_MODEL` | `qwen3:30b-a3b` | MoE, ~3B active params → fast first token. Try `gemma3:12b`, `mistral-small3.2` |
| `KERSTIN_STT_BACKEND` | `http` | `http` = your running Whisper server (OpenAI-compatible); `local` = faster-whisper in-process |
| `KERSTIN_TTS_BACKEND` | `piper` | `http` for a Kokoro-German server, `none` for text only |
| `KERSTIN_OLLAMA_KEEP_ALIVE` | `10m` | frees the shared GPU when idle |

## Project docs

| File | Purpose |
|---|---|
| `CLAUDE.md` | Instructions for Claude Code (lead / reviewer) |
| `AGENTS.md`, `.kilocode/rules/` | Instructions for Kilo Code (worker) |
| `docs/ARCHITECTURE.md` | Components and turn flow |
| `docs/PROTOCOL.md` | WebSocket message contract |
| `docs/ROADMAP.md` | Phases and task IDs |
| `docs/WORKFLOW.md` | Lead ↔ worker loop, task format, review |
| `docs/STATUS.md` | What works, what is unverified |
| `docs/DECISIONS.md` | Decision log |
| `docs/LICENSES.md` | Component licenses (matters if Kerstin goes public) |
| `docs/tasks/` | Task specs for Kilo Code |
