# Kerstin

A local, real-time German speaking partner at **B2 level**. You talk; Kerstin — a fellow B2 learner from Göteborg living in Berlin — talks back, asks follow-up questions and disagrees with you. She does **not** correct you mid-conversation; at the end you get a short feedback report.

Runs entirely on the Dell Pro Max GB10: **Whisper** (speech-to-text) → **Ollama** (LLM) → **Piper** (German TTS), with a browser client.

```
Browser (mic + Silero VAD) ──PCM──▶ FastAPI /ws ──▶ Whisper ──▶ Ollama (stream) ──▶ sentence splitter ──▶ Piper ──WAV──▶ Browser
```

## Quickstart (on the GB10)

```bash
make setup          # venv + deps, creates .env from .env.example
make voice          # download de_DE-thorsten-medium Piper voice
make vendor         # download pinned browser VAD/ONNX assets into frontend/vendor
ollama pull gemma4:26b
# edit .env: point KERSTIN_STT_URL at your Whisper server
make check          # Ollama, STT, voice, GPU temperature
make run            # http://127.0.0.1:8770
make test           # unit tests, no GPU needed
```

## Using it from the Mac / phone (HTTPS)

The browser only allows the microphone on `localhost` or HTTPS. Kerstin can serve HTTPS itself on the LAN with a small local CA (D010); no SSH tunnel and no nginx changes are needed.

On the GB10:

```bash
make certs          # creates certs/ (gitignored), reuses the CA on later runs
# add to .env:
#   KERSTIN_HOST=0.0.0.0
#   KERSTIN_TLS_CERTFILE=certs/kerstin.crt
#   KERSTIN_TLS_KEYFILE=certs/kerstin.key
#   KERSTIN_TLS_CA_CERTFILE=certs/kerstin-ca.crt
make run
```

`KERSTIN_HOST=0.0.0.0` makes Kerstin reachable from the LAN (and NordVPN Meshnet peers) **with no auth** — use it only on a trusted home network.

Trust the CA once per device. Download it from `https://promaxgb10-6116.local:8770/kerstin-ca.crt` (the browser warns this one time because the CA is not trusted yet) or copy it with `scp`:

- **macOS:** open the certificate → Keychain Access → System → the cert → Trust → “Always Trust”. Chrome and Safari use this; Firefox needs its own import or `security.enterprise_roots.enabled=true`.
- **iOS:** open the URL in Safari → install the profile → Settings → General → About → Certificate Trust Settings → enable it.
- **Android:** Settings → Security → Encryption & credentials → Install a certificate → CA certificate.

Then open `https://promaxgb10-6116.fritz.box:8770` (the FritzBox's DNS name; requires `make certs CERTS_ARGS="--dns promaxgb10-6116.fritz.box"`) or `https://promaxgb10-6116.local:8770`. On the GB10, avahi also advertises Docker bridge addresses for `.local`, so that name can point the Mac to an address it can't reach. If both names fail, use `https://192.168.178.55:8770`.

Fallback to the SSH tunnel (plain HTTP on localhost):

```bash
ssh -N -L 8770:127.0.0.1:8770 promaxgb10-6116
# then open http://localhost:8770 on the Mac
```

- **Lautsprecher-Modus (Standard):** das Mikrofon pausiert, während Kerstin spricht. Mit der **Leertaste** (oder „Unterbrechen“) stoppst du sie und sprichst weiter.
- **Kopfhörer-Modus:** einfach dazwischenreden — wie bisher.

## Configuration

All settings are `KERSTIN_*` environment variables (see `.env.example`, defined in `backend/kerstin/config.py`). Most important:

| Setting | Default | Notes |
|---|---|---|
| `KERSTIN_OLLAMA_MODEL` | `gemma4:26b` | ~17 GB while loaded; best German in T015 (5 % vs 18 % error rate) and fastest first audio. Lighter alternative: `qwen3:14b` (D015) |
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
