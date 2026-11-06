# T012 — Kokoro German TTS (sidecar, CPU vs GPU) + A/B against Piper

**Branch:** `task/T012-kokoro-tts` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
Kerstin can speak through a German Kokoro-82M voice instead of Piper by setting `KERSTIN_TTS_BACKEND=http`. A measured A/B (latency on **CPU and GPU**, resource use, intelligibility, plus a blind listening pack for Sameer) shows whether that is worth it and on which device. **The default stays Piper.** Switching the default is Sameer's decision after listening (a later DECISIONS entry).

## Context
- `backend/kerstin/tts.py`: `HttpTTS` already POSTs `{"model", "voice", "input", "response_format": "wav"}` to `<KERSTIN_TTS_URL>/v1/audio/speech` and plays the returned WAV. Config: `tts_url` (default `http://127.0.0.1:8880`, port is free), `tts_model`, `tts_voice` (default `martin`). The browser uses `decodeAudioData`, so a 24 kHz WAV plays fine.
- Persona: Kerstin is a **31-year-old woman** from Göteborg (`backend/prompts/persona.md`). Today she speaks with Thorsten's male Piper voice. A female voice is a real product improvement if quality holds.
- Upstream Kokoro has no German. German comes from community fine-tunes that need the **German forks** `semidark/misaki` (German G2P via espeak-ng) and `semidark/kokoro`. espeak-ng 1.51 is already installed system-wide (`libespeak-ng1`, `espeak-ng-data`); **no `apt`/`sudo`**. If the fork insists on something not installed, stop and report.
- Known Kokoro-German quirk: misaki can emit `ʏ` (short ü), which is not in Kokoro's vocabulary. Replace it with `y` after G2P (as in the Thorsten-Voice `inference.py`).
- **Candidate voices** (check each model card and LICENSE at a pinned revision; record exactly what it says):
  1. `Thorsten-Voice/Kokoro`: `model.pth` (default epoch 5) + `voices/thorsten.pt` + `config.json`. Male, same speaker as the current Piper voice, so this is the clean engine-vs-engine comparison. Apache-2.0, Thorsten dataset CC0.
  2. `cryptomilk/kokoro-german-kerstin`: female, trained on the CC0 "Kerstin 1.0" corpus, Apache-2.0. Its card shows `KModel()` (the stock English weights) + the `df_kerstin.pt` voicepack. Also try the stage-2 weights if the card or kikiri-tts docs give a documented way to load them. Report which combination you used and how it sounds. Drop it if neither works.
  3. `kikiri-tts/kikiri-german-victoria`: female, Apache-2.0.
  - **Excluded:** `kikiri-german-martin` and `-bernd`. Martin's card says the speaker is "synthetic" with unclear provenance, and the Bernd/Tundragoon lineage was deleted upstream. Don't download them.
- **Device: measure, don't assume.** Kokoro is 82M parameters. On the GPU it adds a short burst per reply sentence, next to the 26B LLM that already runs every turn. It could cut TTS time a lot (D013 latency gap). On the CPU it competes with Piper, Uvicorn and other services on the shared Grace cores. The sidecar therefore supports both (`KOKORO_DEVICE=cpu|cuda`) and the A/B measures both. Sameer picks the device from the numbers.
- **GPU rules still apply:** TTS runs only on demand, with no background GPU work. Before every GPU measurement, check `nvidia-smi` and wait if another project is busy. `cool_down()` rule (76 → 70 °C, abort at 80). Report VRAM and peak temperature.
- The Grace CPU is shared, so cap torch threads. The backend stays dependency-light: torch etc. live only in the sidecar's own venv.

## Spec
1. **Sidecar `tts_server/`** (new):
   - `tts_server/core.py`: pure helpers, **no torch import**, so the main test suite can test it:
     - request validation: `input` non-empty and ≤ 600 chars, `response_format` must be `wav`, `speed` 0.7–1.3 (default 1.0), unknown voice → 400;
     - `fix_phonemes(ps: str) -> str` (`ʏ`→`y`);
     - `float_to_wav(samples, rate=24000) -> bytes` (16-bit mono, stdlib `wave` + `array` or numpy; no soundfile).
   - `tts_server/server.py`: FastAPI app.
     - `POST /v1/audio/speech` → `audio/wav`.
     - `GET /health` → `{"ok", "voices", "device", "threads"}`.
     - At startup it loads every voice found under `voices/kokoro/<voice>/`. One `KModel` per voice if the weights differ; reuse it where they don't.
     - One warm-up synthesis per voice.
     - Synthesis runs via `asyncio.to_thread` behind an `asyncio.Lock`: one synthesis at a time, no CPU pile-up.
     - Env: `KOKORO_DEVICE` (`cpu` default until Sameer decides, or `cuda`). With `cuda` but no working CUDA: log an error and exit 1, never silently fall back.
     - Env: `KOKORO_THREADS` (default 4 → `torch.set_num_threads`, CPU path), `KOKORO_HOST` (default `127.0.0.1`, loopback only), `KOKORO_PORT` (default 8880).
     - On `cuda`: no idle GPU work. Models stay loaded (small), but nothing runs between requests. Record the idle VRAM footprint (torch CUDA context + weights).
     - **Must start and run with `HF_HUB_OFFLINE=1`.** No network at runtime; everything is downloaded beforehand.
     - Logs: no input text at INFO (persistent journal, D023). Log voice, chars and ms only.
   - `tts_server/requirements.txt`, everything pinned:
     - a torch **CUDA** wheel for linux-aarch64 that supports the GB10 (NVIDIA GB10, driver 580.178.04, CUDA 13.0 as of 2026-11-06: try the `cu130` index at `https://download.pytorch.org/whl/cu130` first, then `cu128`), exact version. The CUDA wheel also runs on CPU, so one venv covers both devices.
     - **Fallback:** if no CUDA wheel works on the GB10 within reasonable effort (≈1 h, no driver/system changes), use the CPU wheel from `https://download.pytorch.org/whl/cpu`, report what failed, and run the A/B on CPU only;
     - the misaki and kokoro forks as `git+https://…@<commit sha>`;
     - fastapi, uvicorn, numpy.
   - `tts_server/README.md`: setup, run, voices, licenses (short).
2. **Setup:**
   - `make kokoro-setup`: creates `.venv-kokoro` and installs the requirements.
   - `scripts/get_kokoro_voices.sh` (style of `get_voice.sh` / `get_frontend_vendor.sh`):
     - curl from `https://huggingface.co/<repo>/resolve/<pinned commit>/<file>`;
     - SHA-256 pinned per file; on a mismatch delete it and exit 1;
     - only the needed files (no extra epochs, no training checkpoints unless needed for candidate 2);
     - each voice's LICENSE/README is saved next to it;
     - idempotent, `--force`.
   - `make kokoro-voices`, `make kokoro-run`.
   - `.gitignore`: `.venv-kokoro/`, `voices/kokoro/`.
   - Report total disk use.
3. **Kerstin side**, kept minimal:
   - No change to `HttpTTS` unless needed. If a `speed` field is needed for natural pace, add `KERSTIN_TTS_SPEED` (default 1.0), send it, and add a test.
   - `scripts/check_env.sh`: when `KERSTIN_TTS_BACKEND=http`, `[ok] TTS server <url> voices=…` via `GET <url>/health`, else `[FAIL] TTS server unreachable -> make kokoro-run`.
   - `.env.example`: a commented block showing the Kokoro settings.
4. **A/B bench `scripts/tts_ab.py`** (main venv; Piper in-process, Kokoro via HTTP):
   - Input: `scripts/tts_sentences.json` (lead-owned, 30 sentences, `kind` groups; **do not edit it**).
   - Engines: `piper` (thorsten-medium, the current default) + each Kokoro voice that loaded.
   - **Latency:** per sentence, 1 warm-up + 3 timed runs. Report p50/p90 synth ms per engine and per kind, and the real-time factor. The number that matters for D013 is the **short-reply sentences** (`reply` kind): that's what the first-clause path synthesises.
   - **Devices:** each Kokoro voice runs on `cpu` (`KOKORO_THREADS` 4 and 8) and on `cuda`. That's three Kokoro configurations per voice, plus Piper.
   - **Resources:** sidecar RSS (from `/proc/<pid>/status`) and CPU% during each run. For `cuda` also add VRAM idle and peak, GPU utilisation and peak temperature (`nvidia-smi` sampled ~1 Hz during the run).
   - **Intelligibility:** ASR round-trip through Kerstin's existing STT (`make_stt(settings)`; resample 24 kHz → 16 kHz first).
     - Normalise case and punctuation and compute WER per engine.
     - Also list every sentence whose transcript differs, side by side, so number and abbreviation handling ("18:30 Uhr", "12,80 €", "z. B.", "usw.") can be judged by hand.
     - Run the ASR **once** per engine × voice × sentence, not per device: device doesn't change the audio. A spot check of 3 sentences per voice for CPU-vs-GPU audio equality is enough. That's ≤ 120 requests to the shared Whisper server, sequential.
   - **Listening pack:** only with `--out DIR`. It writes `DIR/<random id>.wav` for sentences s02, s09, s13, s17, s20, s22, s25, s27, s29 per engine, plus `DIR/key.json` mapping ids to engines, so Sameer can listen blind. Without `--out`, no audio is written. Use a scratch dir outside the repo; never commit WAVs.
   - Output: a Markdown table to stdout, pasted into the report.
5. **End-to-end check:**
   - Run Kerstin on **8771** with `KERSTIN_TTS_BACKEND=http KERSTIN_TTS_VOICE=<best female voice>`.
   - `scripts/latency_bench.py --url …:8771 --runs 1` three times: piper, http with sidecar on `cpu`, http with sidecar on `cuda`. Report `tts_first_ms` and `first_audio_ms` p50/p90 for each, plus peak GPU temperature per run (LLM + TTS together on the GPU is the realistic case).
   - This uses the LLM (GPU): check `nvidia-smi` first, wait if another project is busy, `cool_down()` rule, one pass each.
6. **Docs:**
   - `docs/LICENSES.md`: rows for `kokoro` fork, `misaki` fork, espeak-ng (GPL-3.0, ⚠️ same situation as Piper), torch (BSD-3), and each voice (weights license + dataset license, from the files you saved). Replace the vague "Kokoro-82M German ports" row.
   - `docs/ARCHITECTURE.md`: TTS row mentions the sidecar.
   - `README.md`: an optional "Kokoro voice" section.
   - `docs/STATUS.md`: one line.
7. **Tests** (main venv, no torch, no network):
   - `backend/tests/test_tts_server_core.py`: validation cases, `fix_phonemes`, and the WAV header of `float_to_wav` (rate, channels, sample width, clipping of ±1.5 input). Import `tts_server/core.py` via path.
   - Tests for the pure parts of `tts_ab.py` (normalisation, WER on a known pair).

## Files allowed to change
- `tts_server/` (new: `core.py`, `server.py`, `requirements.txt`, `README.md`)
- `scripts/get_kokoro_voices.sh` (new), `scripts/tts_ab.py` (new), `scripts/check_env.sh`
- `Makefile`, `.gitignore`, `.env.example`
- `backend/kerstin/tts.py`, `backend/kerstin/config.py` (only for `KERSTIN_TTS_SPEED` if needed)
- `backend/tests/test_tts_server_core.py`, `backend/tests/test_tts_ab.py` (new), `backend/tests/test_tts.py` (if speed is added)
- `README.md`, `docs/LICENSES.md`, `docs/ARCHITECTURE.md`, `docs/STATUS.md` (one line), this task file
- **Not** `scripts/tts_sentences.json` (lead-owned).

## Out of scope / hard rules
- No change to the default backend (stays `piper`) or to `KOKORO_DEVICE`'s default (`cpu`); both wait for Sameer's decision. No change to prompts, the sentence splitter or VAD.
- No `sudo`/`apt`. No systemd unit for the sidecar (a later task if Kokoro wins). Port 8880 (sidecar) and 8771 (Kerstin) only; never touch 8770 or other services.
- Downloads: only the files listed above. Total well under 20 GB (expected < 8 GB including CUDA torch). Stop and ask if anything needs more than ~10 GB.
- No driver, CUDA toolkit or system package changes for the GPU path. If CUDA torch needs one, take the CPU fallback.
- No learner audio or text on disk. Synthesised fixed sentences are written only with an explicit `--out`.

## Acceptance criteria
- [ ] `make test` and `make lint` pass. The main venv has no torch (`.venv/bin/python -c "import torch"` fails).
- [ ] `make kokoro-setup && make kokoro-voices` works on a clean checkout. A second `kokoro-voices` run is a no-op. A corrupted hash exits 1 and leaves no partial file. Paste the disk use.
- [ ] `HF_HUB_OFFLINE=1 make kokoro-run` starts, and `curl -s localhost:8880/health` lists the loaded voices. Paste it.
- [ ] Device check: with `KOKORO_DEVICE=cpu`, `nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv` shows **no** sidecar process. With `cuda` it shows the sidecar and its VRAM. Paste both (or the CUDA failure + fallback note).
- [ ] A/B table pasted: latency p50/p90 per engine, voice, device and kind; RTF; RSS and CPU% (cpu 4/8 threads); VRAM idle/peak, GPU util and peak °C (cuda); WER; the differing-transcript list.
- [ ] End-to-end on 8771 with the http backend: one full exchange plays Kokoro audio (smoke test passes), plus the three-way `latency_bench` comparison (piper / cpu / cuda) with peak °C.
- [ ] Listening pack written to a scratch dir. Its path is in the report (not committed).
- [ ] LICENSES rows filled from the saved license files. Every voice's weights and data are commercially usable, or the voice is dropped.
- [ ] Worker report filled in, incl. new dependencies (sidecar venv only) and their licenses.

## Worker report (Kilo Code fills this in)
- **Changed files:**
- **How tested:**
- **Measurements (if any):**
- **Deviations from spec / extra files touched:**
- **New dependencies (+license):**
- **Open questions:**

## Review (Claude Code fills this in)
- **Verdict:** accept / revise
- **Notes:**
