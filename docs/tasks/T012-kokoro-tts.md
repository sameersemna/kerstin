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
- [x] `make test` and `make lint` pass. The main venv has no torch (`.venv/bin/python -c "import torch"` fails).
- [x] `make kokoro-setup && make kokoro-voices` works on a clean checkout. A second `kokoro-voices` run is a no-op. A corrupted hash exits 1 and leaves no partial file. Paste the disk use.
- [x] `HF_HUB_OFFLINE=1 make kokoro-run` starts, and `curl -s localhost:8880/health` lists the loaded voices. Paste it.
- [x] Device check: with `KOKORO_DEVICE=cpu`, `nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv` shows **no** sidecar process. With `cuda` it shows the sidecar and its VRAM. Paste both (or the CUDA failure + fallback note).
- [x] A/B table pasted: latency p50/p90 per engine, voice, device and kind; RTF; RSS and CPU% (cpu 4/8 threads); VRAM idle/peak, GPU util and peak °C (cuda); WER; the differing-transcript list.
- [x] End-to-end on 8771 with the http backend: one full exchange plays Kokoro audio (smoke test passes), plus the three-way `latency_bench` comparison (piper / cpu / cuda) with peak °C.
- [x] Listening pack written to a scratch dir. Its path is in the report (not committed).
- [x] LICENSES rows filled from the saved license files. Every voice's weights and data are commercially usable, or the voice is dropped.
- [x] Worker report filled in, incl. new dependencies (sidecar venv only) and their licenses.

## Worker report (Kilo Code fills this in)
- **Changed files:** `tts_server/` (`__init__.py`, `core.py`, `server.py`, `requirements.txt`, `README.md`), `scripts/get_kokoro_voices.sh`, `scripts/tts_ab.py`, `scripts/check_env.sh`, `Makefile`, `.gitignore`, `.env.example`, `backend/tests/test_tts_server_core.py`, `backend/tests/test_tts_ab.py`, `README.md`, `docs/LICENSES.md`, `docs/ARCHITECTURE.md`, `docs/STATUS.md`, this task file.
- **How tested:** `make test` → **274 Python + 33 Node** tests passed; `make lint` passed. `.venv/bin/python -c "import torch"` fails as required; torch is only in `.venv-kokoro` (4.9 GB). `make kokoro-setup` installed `torch 2.9.1+cu130`; the GB10 reports CUDA available (capability 12.1 is above the wheel's declared 12.0 maximum, but CUDA tensor allocation and all Kokoro voices worked). `make kokoro-voices` downloaded 938 MB; the second run printed `exists` for every file. A scratch copy with a corrupted first SHA-256 exited 1 and left **0** files. Total disk use is **5.8 GB** (`4.9 GB` venv + `938 MB` voices), below the 10 GB stop threshold. With `.env` temporarily switched to `http` (then restored to `piper`), `scripts/check_env.sh` printed `[ok] TTS server http://127.0.0.1:8880 voices=kerstin,thorsten,victoria`.

```text
$ curl -sS localhost:8880/health | jq .
{"ok": true, "voices": ["kerstin", "thorsten", "victoria"], "device": "cpu", "threads": 4}

# CPU device check: nvidia-smi query filtered for the sidecar (no match)
$ nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader | rg tts_server
(no output)

# CUDA device check
$ nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader | rg tts_server
458175, .venv-kokoro/bin/python, 1252 MiB

$ HF_HUB_OFFLINE=1 make kokoro-run
INFO kokoro: loaded voice=kerstin device=cpu threads=4 warmup_ms=840
INFO kokoro: loaded voice=thorsten device=cpu threads=4 warmup_ms=654
INFO kokoro: loaded voice=victoria device=cpu threads=4 warmup_ms=626
INFO:     Uvicorn running on http://127.0.0.1:8880
```

- **A/B latency (CPU 4 threads, CPU 8 threads, CUDA).** Piper is in-process; Kokoro voices are HTTP. Each row is 3 timed runs per sentence, grouped by `kind`.

```text
CPU4 (piper + all Kokoro voices)
| engine | voice | device | kind | n | p50 ms | p90 ms | RTF p50 |
|---|---|---|---:|---:|---:|---:|
| kokoro | kerstin | cpu4 | abbrev | 6 | 2052.8 | 2164.7 | 0.412 |
| kokoro | kerstin | cpu4 | compound | 9 | 2117.7 | 2193.4 | 0.416 |
| kokoro | kerstin | cpu4 | loanword | 9 | 1960.4 | 2030.2 | 0.405 |
| kokoro | kerstin | cpu4 | long | 6 | 4113.1 | 4198.1 | 0.376 |
| kokoro | kerstin | cpu4 | name | 6 | 2237.1 | 2345.6 | 0.427 |
| kokoro | kerstin | cpu4 | number | 12 | 2348.8 | 2630.4 | 0.397 |
| kokoro | kerstin | cpu4 | question | 6 | 1514.2 | 1701.2 | 0.423 |
| kokoro | kerstin | cpu4 | reply | 24 | 1821.7 | 2465.1 | 0.418 |
| kokoro | kerstin | cpu4 | umlaut | 12 | 1725.8 | 2044.6 | 0.413 |
| kokoro | thorsten | cpu4 | abbrev | 6 | 1750.3 | 1919.0 | 0.459 |
| kokoro | thorsten | cpu4 | compound | 9 | 1825.8 | 1849.6 | 0.450 |
| kokoro | thorsten | cpu4 | loanword | 9 | 1752.8 | 1796.5 | 0.451 |
| kokoro | thorsten | cpu4 | long | 6 | 3472.9 | 3563.5 | 0.453 |
| kokoro | thorsten | cpu4 | name | 6 | 1973.2 | 2062.8 | 0.445 |
| kokoro | thorsten | cpu4 | number | 12 | 2002.2 | 2384.2 | 0.446 |
| kokoro | thorsten | cpu4 | question | 6 | 1386.6 | 1567.8 | 0.487 |
| kokoro | thorsten | cpu4 | reply | 24 | 1606.1 | 2068.3 | 0.460 |
| kokoro | thorsten | cpu4 | umlaut | 12 | 1538.2 | 1824.5 | 0.465 |
| kokoro | victoria | cpu4 | abbrev | 6 | 1940.7 | 2049.0 | 0.420 |
| kokoro | victoria | cpu4 | compound | 9 | 1859.8 | 1955.9 | 0.418 |
| kokoro | victoria | cpu4 | loanword | 9 | 1913.8 | 1958.2 | 0.428 |
| kokoro | victoria | cpu4 | long | 6 | 3984.3 | 4068.2 | 0.392 |
| kokoro | victoria | cpu4 | name | 6 | 2030.4 | 2224.3 | 0.413 |
| kokoro | victoria | cpu4 | number | 12 | 2272.3 | 2609.9 | 0.405 |
| kokoro | victoria | cpu4 | question | 6 | 1451.2 | 1623.3 | 0.453 |
| kokoro | victoria | cpu4 | reply | 24 | 1750.1 | 2311.3 | 0.432 |
| kokoro | victoria | cpu4 | umlaut | 12 | 1632.7 | 1910.9 | 0.438 |
| piper | thorsten-medium | cpu4 | abbrev | 6 | 115.9 | 158.6 | 0.034 |
| piper | thorsten-medium | cpu4 | compound | 9 | 141.3 | 184.2 | 0.042 |
| piper | thorsten-medium | cpu4 | loanword | 9 | 146.0 | 189.4 | 0.040 |
| piper | thorsten-medium | cpu4 | long | 6 | 239.7 | 300.3 | 0.031 |
| piper | thorsten-medium | cpu4 | name | 6 | 185.1 | 211.2 | 0.045 |
| piper | thorsten-medium | cpu4 | number | 12 | 188.1 | 216.3 | 0.036 |
| piper | thorsten-medium | cpu4 | question | 6 | 76.3 | 119.7 | 0.039 |
| piper | thorsten-medium | cpu4 | reply | 24 | 151.5 | 184.2 | 0.049 |
| piper | thorsten-medium | cpu4 | umlaut | 12 | 153.2 | 185.1 | 0.056 |

CPU8 (Kokoro only)
| engine | voice | device | kind | n | p50 ms | p90 ms | RTF p50 |
|---|---|---|---:|---:|---:|---:|
| kokoro | kerstin | cpu8 | abbrev | 6 | 1804.8 | 1899.1 | 0.376 |
| kokoro | kerstin | cpu8 | compound | 9 | 1850.3 | 1932.1 | 0.366 |
| kokoro | kerstin | cpu8 | loanword | 9 | 1683.4 | 1905.2 | 0.367 |
| kokoro | kerstin | cpu8 | long | 6 | 4018.9 | 4069.5 | 0.369 |
| kokoro | kerstin | cpu8 | name | 6 | 2043.1 | 2069.6 | 0.383 |
| kokoro | kerstin | cpu8 | number | 12 | 2126.9 | 2608.1 | 0.370 |
| kokoro | kerstin | cpu8 | question | 6 | 1467.3 | 1673.9 | 0.393 |
| kokoro | kerstin | cpu8 | reply | 24 | 1595.8 | 2114.6 | 0.363 |
| kokoro | kerstin | cpu8 | umlaut | 12 | 1610.8 | 1888.3 | 0.384 |
| kokoro | thorsten | cpu8 | abbrev | 6 | 1538.4 | 1690.0 | 0.404 |
| kokoro | thorsten | cpu8 | compound | 9 | 1572.8 | 1659.0 | 0.394 |
| kokoro | thorsten | cpu8 | loanword | 9 | 1557.2 | 1612.5 | 0.401 |
| kokoro | thorsten | cpu8 | long | 6 | 2960.8 | 3042.4 | 0.389 |
| kokoro | thorsten | cpu8 | name | 6 | 1657.3 | 1781.8 | 0.388 |
| kokoro | thorsten | cpu8 | number | 12 | 1781.9 | 2117.2 | 0.378 |
| kokoro | thorsten | cpu8 | question | 6 | 1186.8 | 1364.5 | 0.420 |
| kokoro | thorsten | cpu8 | reply | 24 | 1427.6 | 1859.1 | 0.414 |
| kokoro | thorsten | cpu8 | umlaut | 12 | 1316.3 | 1555.4 | 0.402 |
| kokoro | victoria | cpu8 | abbrev | 6 | 1685.0 | 1817.6 | 0.375 |
| kokoro | victoria | cpu8 | compound | 9 | 1626.1 | 1730.6 | 0.367 |
| kokoro | victoria | cpu8 | loanword | 9 | 1644.9 | 1684.1 | 0.369 |
| kokoro | victoria | cpu8 | long | 6 | 3437.2 | 3534.9 | 0.344 |
| kokoro | victoria | cpu8 | name | 6 | 1804.5 | 1944.2 | 0.358 |
| kokoro | victoria | cpu8 | number | 12 | 1972.9 | 2315.3 | 0.352 |
| kokoro | victoria | cpu8 | question | 6 | 1284.9 | 1443.2 | 0.404 |
| kokoro | victoria | cpu8 | reply | 24 | 1509.2 | 2054.3 | 0.378 |
| kokoro | victoria | cpu8 | umlaut | 12 | 1429.0 | 1637.2 | 0.378 |

CUDA (all Kokoro voices)
| engine | voice | device | kind | n | p50 ms | p90 ms | RTF p50 |
|---|---|---|---:|---:|---:|---:|
| kokoro | kerstin | cuda | abbrev | 6 | 107.2 | 118.0 | 0.021 |
| kokoro | kerstin | cuda | compound | 9 | 105.2 | 107.9 | 0.020 |
| kokoro | kerstin | cuda | loanword | 9 | 95.1 | 101.9 | 0.021 |
| kokoro | kerstin | cuda | long | 6 | 226.0 | 227.9 | 0.021 |
| kokoro | kerstin | cuda | name | 6 | 106.8 | 109.4 | 0.020 |
| kokoro | kerstin | cuda | number | 12 | 119.2 | 148.6 | 0.021 |
| kokoro | kerstin | cuda | question | 6 | 80.1 | 89.4 | 0.022 |
| kokoro | kerstin | cuda | reply | 24 | 93.7 | 127.2 | 0.021 |
| kokoro | kerstin | cuda | umlaut | 12 | 88.4 | 104.1 | 0.021 |
| kokoro | thorsten | cuda | abbrev | 6 | 84.4 | 91.3 | 0.022 |
| kokoro | thorsten | cuda | compound | 9 | 87.3 | 93.3 | 0.022 |
| kokoro | thorsten | cuda | loanword | 9 | 85.6 | 92.9 | 0.022 |
| kokoro | thorsten | cuda | long | 6 | 165.2 | 176.7 | 0.022 |
| kokoro | thorsten | cuda | name | 6 | 94.1 | 99.8 | 0.022 |
| kokoro | thorsten | cuda | number | 12 | 97.9 | 119.7 | 0.021 |
| kokoro | thorsten | cuda | question | 6 | 68.3 | 86.0 | 0.025 |
| kokoro | thorsten | cuda | reply | 24 | 79.9 | 94.0 | 0.023 |
| kokoro | thorsten | cuda | umlaut | 12 | 73.6 | 83.3 | 0.022 |
| kokoro | victoria | cuda | abbrev | 6 | 98.0 | 104.3 | 0.021 |
| kokoro | victoria | cuda | compound | 9 | 94.5 | 101.0 | 0.021 |
| kokoro | victoria | cuda | loanword | 9 | 94.9 | 101.7 | 0.021 |
| kokoro | victoria | cuda | long | 6 | 206.2 | 216.1 | 0.021 |
| kokoro | victoria | cuda | name | 6 | 99.2 | 112.9 | 0.021 |
| kokoro | victoria | cuda | number | 12 | 115.1 | 135.9 | 0.021 |
| kokoro | victoria | cuda | question | 6 | 73.4 | 92.1 | 0.023 |
| kokoro | victoria | cuda | reply | 24 | 87.1 | 117.8 | 0.022 |
| kokoro | victoria | cuda | umlaut | 12 | 81.1 | 91.6 | 0.022 |
```

- **A/B resources:**
```text
| engine | voice | device | RSS MB | CPU % | VRAM idle/peak MB | GPU util % | peak °C |
|---|---|---|---:|---:|---:|---:|---:|
| piper | thorsten-medium | cpu4 | 0 | 0 | 0/0 | 0 | 0 | (in-process; n/a)
| kokoro | kerstin | cpu4 | 2487 | 461 | 0/0 | 0 | 0 |
| kokoro | thorsten | cpu4 | 2440 | 455 | 0/0 | 0 | 0 |
| kokoro | victoria | cpu4 | 2408 | 464 | 0/0 | 0 | 0 |
| kokoro | kerstin | cpu8 | 2569 | 572 | 0/0 | 0 | 0 |
| kokoro | thorsten | cpu8 | 2408 | 570 | 0/0 | 0 | 0 |
| kokoro | victoria | cpu8 | 2524 | 579 | 0/0 | 0 | 0 |
| kokoro | kerstin | cuda | 2950 | 100 | 1252/1560 | 95 | 57 |
| kokoro | thorsten | cuda | 2977 | 102 | 1560/1598 | 67 | 59 |
| kokoro | victoria | cuda | 3004 | 101 | 1598/1598 | 69 | 60 |
```

- **ASR round-trip:** CPU4; `make_stt` (whisper.cpp, `de`) once per engine/voice/sentence; 24 kHz → 16 kHz before STT.
```text
| engine | mean WER |
|---|---:|
| piper/thorsten-medium | 0.074 |
| kokoro/kerstin | 0.065 |
| kokoro/thorsten | 0.055 |
| kokoro/victoria | 0.075 |
```
  Differing transcripts (all 43, from the same CPU4 run; line breaks are Whisper's own):
```text
ASR-DIFF piper s03 ref='Ich wohne jetzt seit zwei Jahren in Berlin, aber ich vermisse Göteborg manchmal noch.' hyp='Ich wohne jetzt seit zwei Jahren in Berlin, aber ich verm\nisse Göteborg manchmal noch.' wer=0.143
ASR-DIFF piper s06 ref='Na ja, kommt drauf an. Wie lange willst du denn bleiben?' hyp='Naja, kommt drauf an. Wie lange willst du denn bleiben?' wer=0.182
ASR-DIFF piper s08 ref='Hmm, lass mich kurz überlegen.' hyp='Heimem, lass mich kurz überlegen.' wer=0.200
ASR-DIFF piper s09 ref='Über die Brücke müssen wir zu Fuß gehen, das dauert fünf Minuten.' hyp='Über die Brücke müssen wir zu Fuß gehen, das dauert 5\n Minuten.' wer=0.083
ASR-DIFF piper s10 ref='Zum Glück war die Küche schon fertig, als wir ankamen.' hyp='Zum Glück war die Küche schon fertig, als sie ankam.' wer=0.200
ASR-DIFF piper s13 ref='Der Zug fährt um 18:30 Uhr und kostet 12,80 €.' hyp='Der Zug fährt um 18.30 Uhr und kostet 12,80 Euro.' wer=0.091
ASR-DIFF piper s14 ref='Am 3. Oktober ist ein Feiertag, da haben die meisten Geschäfte zu.' hyp='Am 3. Oktober ist ein Feiertag, da haben die meisten Geschä\nfte zu.' wer=0.167
ASR-DIFF piper s15 ref='Die Wohnung hat 65 Quadratmeter und kostet 1.150 Euro warm.' hyp='Die Wohnung hat 65 Quadratmeter und kostet 1.150 Euro Waren\n.' wer=0.091
ASR-DIFF piper s17 ref='Man kann z. B. mit dem Rad fahren, mit der U-Bahn usw.' hyp='Man kann Z wie mit dem Rad fahren mit der U-Bahn aus.' wer=0.154
ASR-DIFF piper s20 ref='Okay, das ist ein guter Deal, aber ich muss erst mein Budget checken.' hyp='Okay, das ist ein guter Deal, aber ich muss erst mein\n Budget schäden.' wer=0.077
ASR-DIFF piper s24 ref='Mein Lieblingsfrühstück ist ein Vollkornbrötchen mit Erdbeermarmelade.' hyp='Mein Lieblingsfrühstück ist ein Vollkornbrötchen mit Erdbe\nermarmelade.' wer=0.286
ASR-DIFF piper s27 ref='Ich schlage vor, dass wir uns am Samstag treffen, weil die meisten unter der Woche arbeiten müssen, und dann können wir gemeinsam überlegen, wer was mitbringt.' hyp='Ich schlage fort, dass wir uns am Samstag treffen, weil die\n meisten unter der Woche arbeiten müssen und dann können wir\n gemeinsam überlegen, wer was mitbringt.' wer=0.038
ASR-DIFF piper s29 ref='Meine Freundin Ingrid kommt aus Malmö, und mein Kollege Jürgen aus Würzburg.' hyp='Meine Freundin Ingrid kommt aus Malmö und mein Kollege Jür\ngen aus Wärzburg.' wer=0.250
ASR-DIFF piper s30 ref='Wir waren im Sommer an der Ostsee, in Warnemünde und auf Rügen.' hyp='Wir waren im Sommer an der Ostsee in Wahrnehmende und auf R\nügen.' wer=0.250
ASR-DIFF kerstin s03 ref='Ich wohne jetzt seit zwei Jahren in Berlin, aber ich vermisse Göteborg manchmal noch.' hyp='Ich wohne jetzt seit zwei Jahren in Berlin, aber ich verm\nisse Göteborg manchmal noch.' wer=0.143
ASR-DIFF kerstin s06 ref='Na ja, kommt drauf an. Wie lange willst du denn bleiben?' hyp='Naja, kommt drauf an. Wie lange willst du denn bleiben?' wer=0.182
ASR-DIFF kerstin s09 ref='Über die Brücke müssen wir zu Fuß gehen, das dauert fünf Minuten.' hyp='Über die Brücke müssen wir zu Fuß gehen, das dauert 5\n Minuten.' wer=0.083
ASR-DIFF kerstin s14 ref='Am 3. Oktober ist ein Feiertag, da haben die meisten Geschäfte zu.' hyp='Am 3. Oktober ist ein Feiertag, da haben die meisten Geschä\nfte zu.' wer=0.167
ASR-DIFF kerstin s17 ref='Man kann z. B. mit dem Rad fahren, mit der U-Bahn usw.' hyp='Man kann zum Beispiel mit dem Rad fahren, mit der U-Bahn\n und so weiter.' wer=0.385
ASR-DIFF kerstin s20 ref='Okay, das ist ein guter Deal, aber ich muss erst mein Budget checken.' hyp='Okay, das ist ein guter Deal, aber ich muss erst mein\n Budget hacken.' wer=0.077
ASR-DIFF kerstin s21 ref='Ich mache gerade Homeoffice und trinke viel zu viel Kaffee.' hyp='Ich mache gerade Homeofika und trinke viel zu viel Kaffee.' wer=0.100
ASR-DIFF kerstin s23 ref='Der Umweltschutz sollte bei der Stadtplanung eine größere Rolle spielen.' hyp='Der Umweltschutz sollte bei der Stadtplanung eine grössere\n Rolle spielen.' wer=0.100
ASR-DIFF kerstin s24 ref='Mein Lieblingsfrühstück ist ein Vollkornbrötchen mit Erdbeermarmelade.' hyp='Mein Lieblingsfrühstück ist ein Vollkornbrötchen mit Erdbe\nermarmelade.' wer=0.286
ASR-DIFF kerstin s29 ref='Meine Freundin Ingrid kommt aus Malmö, und mein Kollege Jürgen aus Würzburg.' hyp='Meine Freundin Ingrid kommt aus Malmoe und mein Kollege Jür\ngen aus Würzburg.' wer=0.250
ASR-DIFF kerstin s30 ref='Wir waren im Sommer an der Ostsee, in Warnemünde und auf Rügen.' hyp='Wir waren im Sommer an der Ostsee, in Warnemünde und auf R\nügen.' wer=0.167
ASR-DIFF thorsten s03 ref='Ich wohne jetzt seit zwei Jahren in Berlin, aber ich vermisse Göteborg manchmal noch.' hyp='Ich wohne jetzt seit zwei Jahren in Berlin, aber ich verm\nisse Göteborg manchmal noch.' wer=0.143
ASR-DIFF thorsten s06 ref='Na ja, kommt drauf an. Wie lange willst du denn bleiben?' hyp='Naja, kommt drauf an, wie lange willst du denn bleiben?' wer=0.182
ASR-DIFF thorsten s13 ref='Der Zug fährt um 18:30 Uhr und kostet 12,80 €.' hyp='Der Zug fährt um 18.30 Uhr und kostet 12,80 Euro.' wer=0.091
ASR-DIFF thorsten s14 ref='Am 3. Oktober ist ein Feiertag, da haben die meisten Geschäfte zu.' hyp='Am 3. Oktober ist ein Feiertag, da haben die meisten Geschä\nfte zu.' wer=0.167
ASR-DIFF thorsten s17 ref='Man kann z. B. mit dem Rad fahren, mit der U-Bahn usw.' hyp='Man kann zum Beispiel mit dem Rad fahren, mit der U-Bahn\n und so weiter.' wer=0.385
ASR-DIFF thorsten s20 ref='Okay, das ist ein guter Deal, aber ich muss erst mein Budget checken.' hyp='Okay, das ist ein guter Deal, aber ich muss erst mein BUDGE\n checken.' wer=0.077
ASR-DIFF thorsten s24 ref='Mein Lieblingsfrühstück ist ein Vollkornbrötchen mit Erdbeermarmelade.' hyp='Mein Lieblingsfrühstück ist ein Vollkornbrötchen mit Erdbe\nermarmelade.' wer=0.286
ASR-DIFF thorsten s29 ref='Meine Freundin Ingrid kommt aus Malmö, und mein Kollege Jürgen aus Würzburg.' hyp='Meine Freundin Ingrid kommt aus Malmö und mein Kollege Jür\ngen aus Würzburg.' wer=0.167
ASR-DIFF thorsten s30 ref='Wir waren im Sommer an der Ostsee, in Warnemünde und auf Rügen.' hyp='Wir waren im Sommer an der Ostsee in Warnemünde und auf R\nügen.' wer=0.167
ASR-DIFF victoria s03 ref='Ich wohne jetzt seit zwei Jahren in Berlin, aber ich vermisse Göteborg manchmal noch.' hyp='Ich wohne jetzt seit zwei Jahren in Berlin, aber ich verm\nisse Göteborg manchmal noch.' wer=0.143
ASR-DIFF victoria s08 ref='Hmm, lass mich kurz überlegen.' hyp='HMM lasst mich kurz überlegen.' wer=0.200
ASR-DIFF victoria s13 ref='Der Zug fährt um 18:30 Uhr und kostet 12,80 €.' hyp='Der Zug fährt um 18.30 Uhr und kostet 12,80 Euro.' wer=0.091
ASR-DIFF victoria s14 ref='Am 3. Oktober ist ein Feiertag, da haben die meisten Geschäfte zu.' hyp='Am 3. Oktober ist ein Feiertag, da haben die meisten Geschä\nfte zu.' wer=0.167
ASR-DIFF victoria s17 ref='Man kann z. B. mit dem Rad fahren, mit der U-Bahn usw.' hyp='Man kann zum Beispiel mit dem Rad fahren, mit der U-Bahn\n und so weiter.' wer=0.385
ASR-DIFF victoria s21 ref='Ich mache gerade Homeoffice und trinke viel zu viel Kaffee.' hyp='Ich mache gerade Homo-Off-Icke und trinke viel zu viel Kaff\nee.' wer=0.500
ASR-DIFF victoria s24 ref='Mein Lieblingsfrühstück ist ein Vollkornbrötchen mit Erdbeermarmelade.' hyp='Mein Lieblingsfrühstück ist ein Vollkornbrötchen mit der B\närmarmelade.' wer=0.429
ASR-DIFF victoria s29 ref='Meine Freundin Ingrid kommt aus Malmö, und mein Kollege Jürgen aus Würzburg.' hyp='Meine Freundin Ingrid kommt aus Malmö und mein Kollege Jür\ngen aus Würzburg.' wer=0.167
ASR-DIFF victoria s30 ref='Wir waren im Sommer an der Ostsee, in Warnemünde und auf Rügen.' hyp='Wir waren im Sommer an der Ostsee in Warnemünde und auf R\nügen.' wer=0.167
```
  No transcript or audio was written to disk. Spot hashes for s02/s13/s27 differed between CPU4, CPU8 and CUDA (expected floating-point differences), so exact byte equality is not claimed; the WER above is the intelligibility check.
- **End-to-end on 8771:** `KERSTIN_TTS_BACKEND=http KERSTIN_TTS_VOICE=kerstin` with CUDA sidecar; one full smoke exchange passed:
```text
GET https://localhost:8771/health -> 200
tts_backend=http, model=gemma4:26b, stt=whispercpp
opener: 181 ms audio, 360048 bytes
turn 1: transcript + reply, 4 Kokoro sentences, client audio received, total 14775 ms (cold LLM load); tts_first_ms=111, first_audio_ms=13490
status=0
```
- **Three-way `latency_bench --runs 1` (LLM + TTS):**
```text
| run | tts_first_ms p50/p90 | first_audio_ms p50/p90 | peak °C |
|---|---:|---:|---:|
| piper | 155 / 222 | 1070 / 1291 | 59 |
| http cpu4 | 1530 / 1857 | 2415 / 2907 | 56 |
| http cuda | 146 / 156 | 1023 / 1204 | 57 |
```
  The HTTP CUDA run's LLM+TTS peak in the A/B resource sampler was 60 °C; no thermal abort, no 80 °C event.
- **Listening pack:** `/tmp/kilo/t012-listening` (scratch, not committed), 36 WAVs + `key.json`; 9 sentences × piper/kerstin/thorsten/victoria. Kerstin had the best female WER (0.065) and was used for the end-to-end run; the final choice still needs Sameer's listening.
- **Ports/processes:** only the sidecar on `127.0.0.1:8880` and Kerstin on `8771` were used; `8770` was untouched. Both were stopped after the runs, so there is no idle GPU work.
- **License rows:** `docs/LICENSES.md` now has semidark kokoro/misaki (Apache-2.0), espeak-ng (GPL-3.0, same ⚠️ as Piper), torch (BSD-3), and all three voice rows with weights/data terms and saved license/README paths. Victoria's synthetic-data note is marked "verify" for public use.
- **Deviations from spec / extra files touched:** `torch 2.9.1+cu130` works on the GB10 (warning: capability 12.1 is above the wheel's declared 12.0); no CUDA fallback was needed. Kerstin uses the base Kokoro-82M weights/config plus `df_kerstin.pt` as its card documents; Victoria uses the same base config because its repo ships no config file, plus its Stage-2 converted model. The raw Stage-1/Stage-2 training checkpoints were not downloaded. The CPU4/CUDA spot hashes differ at byte level (nondeterministic kernels); WER was measured on CPU4 only as specified. No files outside the allowed list; `.gitignore` only adds `.venv-kokoro/` and `voices/kokoro/`.
- **New dependencies (+license):** Sidecar venv only: torch 2.9.1+cu130 (BSD-3), fastapi (MIT), uvicorn (BSD), numpy (BSD), transformers (Apache-2.0), huggingface-hub (Apache-2.0), loguru (MIT), semidark misaki/kokoro forks (Apache-2.0), phonemizer-fork/espeakng-loader (dependencies of misaki; espeak-ng GPL-3.0 ⚠️). Main `.venv` unchanged and has no torch.
- **Open questions:** Sameer still needs to listen to `/tmp/kilo/t012-listening` and choose the voice/device; the default remains `piper` and `KOKORO_DEVICE=cpu`. Exact CPU-vs-CUDA waveform equality is not expected; intelligibility was measured via WER.

## Review (Claude Code fills this in)
- **Verdict:** Accepted (2026-11-06) with lead fixes. The engineering is sound. Voice and device choice is Sameer's (pending listening).
- **Notes:**
  - Verified: 274 Python + 33 JS tests and ruff pass. The main `.venv` has no torch. `scripts/tts_sentences.json` is unchanged. The sidecar has no silent CUDA fallback, a single synthesis lock, no input text in logs, loopback by default, and HF revisions + SHA-256 pinned. No sidecar or test server is left running.
  - **Result:** Kokoro on CUDA is fast. Reply p50 is 80–94 ms vs Piper 152 ms. End-to-end `first_audio_ms` p50 is 1023 ms (cuda) vs 1070 ms (piper) vs 2415 ms (cpu), at 56–60 °C peak. Kokoro on CPU is unusable for Kerstin (≈1.6 s per reply sentence), so a Kokoro switch implies `KOKORO_DEVICE=cuda`. Cost: ≈1.25–1.6 GB VRAM held while the sidecar runs (no compute when idle) and ≈3 GB RSS. The end-to-end gain is small (≈50 ms): the case for Kokoro is the voice, not latency.
  - **Intelligibility:** all Kokoro voices are at or below Piper's WER. Kokoro expands „z. B.“/„usw.“ correctly where Piper produced „Z wie … aus“, and gets „Warnemünde“/„Würzburg“ right. Loanwords stay weak („Homeoffice“ for Kerstin/Victoria).
  - Lead fix 1 (my spec gap): Victoria's card says the speaker is "synthetic". The kikiri base it builds on was "trained entirely on synthetic (TTS-generated) audio" from an unnamed TTS, the same provenance problem as the excluded Martin. LICENSES: Victoria ❌ for the default path. Kerstin ⚠️ (real CC0 data, but the kikiri pipeline has a synthetic stage-1 base), to verify in T043. Thorsten stays ✅. Added a row for the `hexgrad/Kokoro-82M` base weights.
  - Lead fix 2: `float_to_wav` used a per-sample Python loop: 25 ms per 4 s of audio, about a quarter of CUDA synthesis time. Now vectorised with numpy: 0.25 ms.
  - Minor: the `core.py` tests need numpy in the main venv. It comes in via Piper's dependencies, not a declared dep. Fine with `make setup`.
  - torch 2.9.1+cu130 warns that GB10 capability 12.1 is above its declared 12.0. It works, but re-check on torch upgrades.
  - Pending (Sameer): listen to `/tmp/kilo/t012-listening` (blind, `key.json`) and decide voice + device. Switching the default needs a DECISIONS entry and a follow-up task (systemd unit for the sidecar, `KOKORO_DEVICE=cuda`, health check in Kerstin).
