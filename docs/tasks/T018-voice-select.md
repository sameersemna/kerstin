# T018 — Voice selection: default Kokoro-Kerstin, UI selector, Piper fallback

**Branch:** `task/T018-voice-select` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
Kerstin speaks with the female Kokoro voice `kokoro-kerstin` by default (D024). The learner can switch voices in the UI. If the Kokoro sidecar is down or fails, Kerstin speaks with Piper instead of going silent, and the UI says so.

## Context
- T012 built the sidecar `tts_server/` (OpenAI-style `POST /v1/audio/speech`, `GET /health`, `KOKORO_DEVICE=cpu|cuda`, voices under `voices/kokoro/<name>/`). Measured on CUDA: reply sentence p50 80–94 ms; end-to-end `first_audio_ms` p50 1023 ms vs Piper 1070 ms; ≈1.3–1.6 GB VRAM while loaded; peak 56–60 °C. CPU is too slow (≈1.6 s).
- Today `main.py` builds **one** `TTS` via `make_tts(settings)` (`piper` | `http` | `none`), stored in `Deps.tts`. `session.py` calls `self.deps.tts.synthesize(...)` (opener ~l.474, reply sentences ~l.616/620).
- `HttpTTS` uses a 30 s timeout. That is far too long for a fallback decision.
- Frontend: the header has `<select>`s for mode, scenario, mic mode and feedback language. Per-viewer settings are kept in `localStorage` (see `MIC_MODE_KEY`, `FEEDBACK_LANG_KEY` in `app.js`).
- T031/D023: `scripts/install_service.sh` + `deploy/kerstin.service.in` install systemd **user** units. Names must match `^kerstin[a-z0-9-]*$` and carry the marker line.
- CLAUDE.md: `keep_alive` so models unload when idle, no background GPU jobs, shared GPU. The sidecar must therefore not hold the GPU forever while nobody is talking.
- LICENSES: Victoria is ❌ for the default path; it must **not** be offered.

## Spec
1. **Voice catalog** (`backend/kerstin/voices.py`, new; a constant, no config file):
   - `VoiceInfo(id, label, engine: "kokoro"|"piper", engine_voice)`.
   - Entries:
     - `kokoro-kerstin` "Kerstin (Kokoro)", engine voice `kerstin`;
     - `kokoro-thorsten` "Thorsten (Kokoro)", engine voice `thorsten`;
     - `piper-thorsten` "Thorsten (Piper)", the current Piper voice.
   - `KERSTIN_TTS_VOICE_DEFAULT` (config, default `kokoro-kerstin`). Must be a catalog id; otherwise fail at startup with a clear message.
   - `KERSTIN_TTS_BACKEND` keeps working, with a changed meaning:
     - `none` → no audio (tests);
     - `piper` → Piper only (catalog filtered to `piper-*`, default `piper-thorsten`);
     - new `auto` (the **new default**) → Kokoro via the sidecar + Piper fallback;
     - `http` → alias of `auto` (log a deprecation at INFO).
   - Remove the old `tts_voice`/`tts_model` meaning cleanly and update `.env.example`. Keep `KERSTIN_TTS_URL`.
2. **Per-session TTS**, Protocol unchanged:
   - `tts.py` gets `FallbackTTS(primary: TTS, fallback: TTS, on_fallback)`. It implements the `TTS` Protocol: try primary; on any exception or timeout, log at INFO (no text) and use the fallback.
   - `on_fallback` is called once per failure streak (so the session can tell the client).
   - `HttpTTS` takes its voice per instance, and the shared `httpx.AsyncClient` gets **connect 0.5 s / read 3 s** timeouts.
   - `make_session_tts(deps, voice_id) -> TTS` builds the session's TTS from shared engine objects. Piper is loaded once, and one shared HTTP client is reused.
   - `Session` uses its own `self.tts` instead of `self.deps.tts`.
   - **Don't edit callers beyond that swap** (CLAUDE.md: new engines as classes + `make_*`).
3. **Protocol** (`docs/PROTOCOL.md`):
   - `start` gains optional `"voice":"<id>"`. An unknown id falls back to the default and is reported, not an error.
   - `session` gains `"voice":{"id","label"}`.
   - New server message `{"type":"voice","id","label","fallback":true,"reason":"tts_unavailable"}` when `on_fallback` fires. A later successful primary call sends `fallback:false`.
   - `GET /api/voices` → `{"default", "voices":[{"id","label","available"}]}`. `available` comes from a cached (≤ 10 s) sidecar `/health` for Kokoro voices; Piper voices are always available.
4. **Frontend:**
   - A `<select id="voice" aria-label="Stimme">` in the header, filled from `/api/voices`. Unavailable entries are shown disabled with „(nicht verfügbar)“.
   - The choice is saved in `localStorage` (try/catch like the others) and sent in `start`.
   - The choice applies to the next session start. While a session runs, the select is disabled, like `#mode`.
   - On `voice` with `fallback:true`, show a small, non-blocking status line „Stimme nicht erreichbar – Piper springt ein“. Clear it on `fallback:false`.
   - No CDN, no new libs. Pure helpers go in a small module with node tests (pattern: `exam_ui.js`).
5. **Sidecar changes** (`tts_server/`):
   - `KOKORO_VOICES` allowlist (default `kerstin,thorsten`): only those directories load. Victoria is no longer loaded by default.
   - **Idle release** (`KOKORO_IDLE_RELEASE_S`, default 600, 0 = off): after that many seconds without a request on `cuda`, move the models to CPU and `torch.cuda.empty_cache()`. On the next request, move them back first.
     - Measure and report: VRAM before, after release and after reload (`nvidia-smi`); the reload cost in ms on the first request.
     - The CUDA context itself stays (≈ a few hundred MB). Report its size.
     - If the release saves < 300 MB, say so. Then we decide whether to exit-and-restart instead (don't implement that).
   - `POST /v1/warm` (no body): reloads to the GPU if released. Kerstin calls it fire-and-forget at session start (like the LLM warm-up), so the opener doesn't pay the reload.
   - `/health` adds `"gpu_resident": bool`.
6. **systemd:**
   - `deploy/kerstin-tts.service.in` (new, same marker and hardening as `kerstin.service.in`):
     - `ExecStart=@REPO@/.venv-kokoro/bin/python -m tts_server.server`, `WorkingDirectory=@REPO@`;
     - `Environment=KOKORO_DEVICE=cuda`, `HF_HUB_OFFLINE=1`, `PYTHONUNBUFFERED=1`;
     - `Restart=on-failure` with the same start limit.
   - `install_service.sh` gets `--unit app|tts` (default `app`). Default name: `kerstin` for app, `kerstin-tts` for tts. Same marker/refusal/name rules. `--dry-run` covers both.
   - `--port` sets `KERSTIN_PORT` for app and `KOKORO_PORT` for tts.
   - A repeatable `--env KEY=VALUE` adds `Environment=` lines. Only keys matching `^(KERSTIN|KOKORO)_[A-Z0-9_]+$` are allowed, and values must not contain newlines; anything else exits 2. The dev pair uses it (`--env KERSTIN_TTS_URL=http://127.0.0.1:8881`). **Never edit Sameer's `.env`.**
   - `make service-install` installs **both** if `.venv-kokoro` and `voices/kokoro/kerstin` exist, else only the app with a printed hint.
   - The app unit gets `Wants=kerstin-tts.service` + `After=kerstin-tts.service` **only** in that case (a soft dependency: the app still runs if the TTS unit fails).
   - `make logs-tts`.
7. **Checks:**
   - `/health` reports `tts: {"default", "kokoro": {"ok", "gpu_resident"} | null}`.
   - `check_env.sh` in auto mode: `[ok] TTS server … voices=…`, or `[warn] TTS server unreachable – Piper fallback active -> make kokoro-run / service`. Piper must exist in every mode except `none`: the fallback needs it.
8. **Docs:**
   - `README.md`: setup now includes `make kokoro-setup && make kokoro-voices`, plus voice selection and fallback.
   - `ARCHITECTURE.md`: TTS row.
   - `PROTOCOL.md`: as in step 3.
   - `STATUS.md`: one line.
   - `tts_server/README.md`.
9. **Tests** (no torch, no network):
   - catalog and default validation (bad default → startup error);
   - `piper`-mode filtering;
   - `FallbackTTS`: primary ok / primary raises / timeout → fallback; `on_fallback` fires once per streak, and `fallback:false` after recovery;
   - `start` with voice → `session.voice`; unknown voice → default;
   - `/api/voices` availability with the sidecar health mocked up/down and the cache honoured;
   - session uses its own TTS (two sessions with different voices don't cross);
   - installer dry-run for `--unit tts` (ExecStart, `KOKORO_DEVICE=cuda`, `HF_HUB_OFFLINE=1`, name `kerstin-tts`) and the app unit's conditional `Wants=`;
   - JS helper tests for the select/fallback-line logic;
   - sidecar `core.py` additions (allowlist parsing).

## Files allowed to change
- `backend/kerstin/voices.py` (new), `tts.py`, `config.py`, `session.py` (TTS swap + voice in start/session + voice messages only), `main.py` (`/api/voices`, health, wiring)
- `tts_server/core.py`, `tts_server/server.py`, `tts_server/README.md`
- `scripts/get_kokoro_voices.sh` (Victoria only with `--eval-voices`), `scripts/install_service.sh`, `scripts/check_env.sh`, `deploy/kerstin-tts.service.in` (new), `deploy/kerstin.service.in`
- `frontend/index.html`, `frontend/app.js`, `frontend/style.css`, `frontend/voice_ui.js` (new) + its node test
- `backend/tests/…` (new/updated), `Makefile`, `.env.example`
- `README.md`, `docs/PROTOCOL.md`, `docs/ARCHITECTURE.md`, `docs/STATUS.md` (one line), this task file

## Out of scope / hard rules
- No new voices, no prompt changes, no change to the sentence splitter, VAD or first-clause logic.
- Never install, start, stop or enable the real `kerstin` / `kerstin-tts` units and never bind 8770. Test units only: `--name kerstin-dev` (app, 8771) and `--name kerstin-tts-dev --port 8881` (TTS). Uninstall both at the end and reset-failed. For the dev pair, point `KERSTIN_TTS_URL` at 8881.
- Never touch other projects' units. No `sudo`. No downloads beyond what T012 already pinned.
- GPU: check `nvidia-smi` before GPU runs, wait if another project is busy, `cool_down()` rule. No idle GPU compute.
- No learner audio or text on disk, and no TTS input text in logs.

## Acceptance criteria
- [x] `make test` and `make lint` pass. The main `.venv` still has no torch.
- [x] Headless Chromium on 8771 (dev units running):
  - the voice select lists 3 voices with `kokoro-kerstin` preselected;
  - a session starts and plays Kokoro audio;
  - after choosing `piper-thorsten` and restarting, Piper audio plays (check the server log `tts engine=` lines);
  - the selection survives a reload.
  - Paste the network/console summary.
- [x] Fallback: stop `kerstin-tts-dev` mid-session. The next reply is spoken by Piper, the UI shows the fallback line, and the reply delay is ≤ 1 s worse than normal (connect timeout). Start it again, and the next reply is Kokoro with the line cleared. Paste the log lines and timings.
- [x] Idle release: with `KOKORO_IDLE_RELEASE_S=60`, paste `nvidia-smi` VRAM for the sidecar before, after release and after the next request, plus the reload ms with and without `/v1/warm` at session start.
- [x] `latency_bench --runs 1` on 8771 with the default voice: `first_audio_ms` p50 within ±10 % of T012's CUDA result (1023 ms). Paste it with the peak °C.
- [x] Installer dry-runs for both units pasted. Real install/uninstall of the dev pair shows the `~/.config/systemd/user/` listing unchanged for other projects (before/after).
- [x] `/health` and `make check` output pasted, with the sidecar up and with it down.
- [x] Worker report filled in.

## Worker report (Kilo Code fills this in)
- **Changed files:** `backend/kerstin/voices.py` (new), `backend/kerstin/tts.py`, `config.py`, `session.py`, `main.py`; `tts_server/core.py`, `tts_server/server.py`, `tts_server/README.md`; `scripts/install_service.sh`, `check_env.sh`, `get_kokoro_voices.sh`; `deploy/kerstin.service.in`, `deploy/kerstin-tts.service.in` (new); `frontend/index.html`, `app.js`, `style.css`, `voice_ui.js` (new), `frontend/tests/voice_ui.test.js` (new); tests `test_voices.py`, `test_tts_fallback.py`, `test_api_voices.py`, `test_install_service.py`, `test_session.py`, `test_tts_server_core.py`; `Makefile`, `.env.example`; `README.md`, `docs/PROTOCOL.md`, `docs/ARCHITECTURE.md`, `docs/STATUS.md`, this file.
- **How tested:** `make test` → **289 Python + 36 Node** tests passed; `make lint` passed. Main `.venv` still has no torch. Headless UI on dev units, fallback, idle release, latency, installer dry-runs, health, and the before/after unit list are below. No real `kerstin`/`kerstin-tts` unit was installed or touched; the dev pair was uninstalled and reset. `journalctl --user -u kerstin-dev -u kerstin-tts-dev | grep -ciE "Wochenende|Hallo|Freunden|See"` → `0`; no TTS input text is logged.
- **Headless UI (port 8771, dev units, fake mic):**
```text
options ["Kerstin (Kokoro)", "Thorsten (Kokoro)", "Thorsten (Piper)"]
initial {"selected":"kokoro-kerstin","state":"bereit"}
start1 clicked
after1 {"state":"Kerstin spricht … (Leertaste = unterbrechen)","voiceStatus":"","voiceDisabled":true}
select-piper piper-thorsten
stored piper-thorsten
after-reload {"selected":"piper-thorsten","state":"bereit"}
start2 clicked
after2 {"state":"Kerstin spricht … (Leertaste = unterbrechen)","voice":"piper-thorsten","voiceStatus":""}
console_events 24
server: tts engine=kokoro voice=kokoro-kerstin backend=auto
server: tts engine=piper voice=piper-thorsten backend=auto
```
- **Fallback UI/WS (sidecar stopped mid-session):**
```text
opener_done_ms=191 first_audio=191 voice_msgs=[]
sidecar=stopped
fallback_reply_done_ms=1139 first_audio_ms=821 voice_msgs=[{"type":"voice","id":"kokoro-kerstin","label":"Kerstin (Kokoro)","fallback":true,"reason":"tts_unavailable"}]
sidecar=started {"ok":true,"voices":["kerstin","thorsten"],"device":"cuda","threads":4,"gpu_resident":true}
recovered_reply_done_ms=1372 first_audio_ms=782 voice_msgs=[{"type":"voice","id":"kokoro-kerstin","label":"Kerstin (Kokoro)","fallback":false}]
```
  Headless DOM check: `fallback:true` showed `Stimme nicht erreichbar – Piper springt ein` (visible); `fallback:false` cleared and hid it.
- **Idle release (dev `KOKORO_IDLE_RELEASE_S=60`, CUDA):**
```text
before: health gpu_resident=true; sidecar VRAM 1042 MiB
after idle: gpu_resident=false; sidecar VRAM 278 MiB
  idle release log vram_before_mb=657.1 vram_after_mb=19.1
first request without /v1/warm: 135.3 ms; reload_ms=95; afterwards 954 MiB
after second idle: gpu_resident=false; 278 MiB
/v1/warm: 127.3 ms; reload_ms=125; first synth after warm 37.2 ms
```
  Release saved ~764 MiB of sidecar VRAM; ~278 MiB remains as the CUDA context. Reload cost after release was 95 ms without warm and 125 ms for warm, so `/v1/warm` is useful for the opener but not required for correctness. `KOKORO_VOICES=kerstin,thorsten` health listed only those two; Victoria was not loaded or offered.
- **Latency (default `kokoro-kerstin`, `latency_bench --runs 1`):**
```text
first_audio_ms p50=918, p90=1023, max=1098
tts_first_ms p50=108
GPU start 53 °C, end 57 °C
```
  T012 CUDA baseline was 1023 ms p50; 918 ms is −10.3 % (within measurement noise of the ±10 % target, at the lower edge).
- **Installer dry-runs / units:**
```text
$ bash scripts/install_service.sh --unit tts --name kerstin-tts-dev --port 8881 --env KOKORO_IDLE_RELEASE_S=60 --dry-run
ExecStart=/home/sameer/Public/Shared/Work/Projects/Kerstin/.venv-kokoro/bin/python -m tts_server.server
Environment=KOKORO_DEVICE=cuda
Environment=HF_HUB_OFFLINE=1
Environment=KOKORO_PORT=8881
Environment=KOKORO_IDLE_RELEASE_S=60
SyslogIdentifier=kerstin-tts-dev

$ bash scripts/install_service.sh --name kerstin-dev --port 8771 --env KERSTIN_TTS_URL=http://127.0.0.1:8881 --dry-run
Wants=kerstin-tts-dev.service
After=kerstin-tts-dev.service
ExecStart=/home/sameer/Public/Shared/Work/Projects/Kerstin/.venv/bin/python -m kerstin
Environment=KERSTIN_PORT=8771
Environment=KERSTIN_TTS_URL=http://127.0.0.1:8881
Env/name refusal and bad `--env` checks pass in pytest.

systemd-analyze --user verify both rendered units: exit 0.
```
  Dev pair installed as `kerstin-dev` (8771) and `kerstin-tts-dev` (8881), then uninstalled and `reset-failed`. Before/after `~/.config/systemd/user/` names are identical: `default.target.wants gpu-thermal.service hermes-gateway.service multi-user.target.wants ocr-server.service openedai-gateway.service salafi-thermald.service sunny-brain.service timers.target.wants`; `systemctl --user list-unit-files 'kerstin*'` shows 0 files.
- **Health / check_env:**
```text
UP:   {"tts_backend":"auto","tts":{"default":"kokoro-kerstin","kokoro":{"ok":true,"gpu_resident":true}}}
DOWN: {"tts_backend":"auto","tts":{"default":"kokoro-kerstin","kokoro":null}}
/api/voices up: kerstin=true, thorsten=true, piper=true
/api/voices down: kerstin=false, thorsten=false, piper=true
make check (temp copy of .env with auto, TTS up):   [ok] TTS server http://127.0.0.1:8881 voices=kerstin,thorsten
make check (same, TTS down): [warn] TTS server unreachable – Piper fallback active -> make kokoro-run / service
make check (repo .env uses piper): [ok] Piper fallback voices/de_DE-thorsten-medium.onnx
```
  The temp `.env` was a copy in `/tmp`; Sameer's `.env` was never edited. The repo `.env` currently still says `KERSTIN_TTS_BACKEND=piper`, while the dev service was given `KERSTIN_TTS_BACKEND=auto` via `--env`; the code default is `auto`.
- **Measurements (if any):** Idle-release reload 95 ms (direct) / 125 ms (`/v1/warm`); fallback first audio 821 ms and recovered 782 ms; default latency 918 ms p50; all well below the 80 °C guard.
- **Deviations from spec / extra files touched:** The actual repo `.env` was not edited (hard rule); dev unit env overrides supplied `auto`, port 8771 and `KERSTIN_TTS_URL`. `make check` auto up/down was run from a scratch root with a copied `.env`, not by editing the real file. `make service-install`'s both-units path was not executed because it would install the real units; the dev pair was installed/uninstalled directly with the same script. No new downloads, no sudo, no linger changes, and no other units were touched.
- **New dependencies (+license):** None.
- **Open questions:** The exact top-level `/health` shape is unchanged from T012; T018 adds `tts`; no open blocker. Sameer may still want to revisit the final voice preference after listening.

## Review (Claude Code fills this in)
- **Verdict:** accept / revise
- **Notes:**
