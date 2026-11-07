# Kokoro German TTS sidecar

Optional OpenAI-compatible Kokoro German TTS server for Kerstin. The default
Kerstin backend is `auto`: Kokoro through this sidecar with Piper fallback.
`KERSTIN_TTS_BACKEND=http` is the legacy alias; set `KERSTIN_TTS_URL` when it is
not on port 8880.

## Setup

```bash
make kokoro-setup     # .venv-kokoro, pinned CUDA torch + German forks
make kokoro-voices    # pinned voice weights under voices/kokoro (gitignored)
HF_HUB_OFFLINE=1 make kokoro-run
curl -s localhost:8880/health
```

`KOKORO_DEVICE` is `cpu` by default; set `cuda` explicitly. A CUDA request
fails at startup instead of falling back to CPU. `KOKORO_THREADS` defaults to
4. The server listens on `127.0.0.1:8880` by default.

`KOKORO_VOICES` is a comma-separated allowlist (default `kerstin,thorsten`);
Victoria is only for explicit evaluations, not production. On CUDA,
`KOKORO_IDLE_RELEASE_S` (default 600, 0 = off) moves the models to CPU and
empties the CUDA cache after idle; `POST /v1/warm` reloads them for the next
session. `/health` reports `gpu_resident`.

## Voices

- `thorsten` — Thorsten-Voice/Kokoro, Apache-2.0, Thorsten-Voice dataset CC0.
- `kerstin` — cryptomilk/kokoro-german-kerstin, Apache-2.0, Kerstin dataset CC0-1.0.
- `victoria` — kikiri-tts/kikiri-german-victoria, Apache-2.0, synthetic Victoria voice.

`make kokoro-voices` saves each repository's license/README next to its weights.
The German G2P comes from the semidark misaki/kokoro forks and needs the system
`libespeak-ng` (already installed); no system packages are changed by Kerstin.
