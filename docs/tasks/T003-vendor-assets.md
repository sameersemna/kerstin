# T003 — Vendor frontend assets (no CDN at runtime)

**Branch:** `task/T003-vendor-assets` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
The page loads the VAD, ONNX runtime and Silero model from Kerstin's own server instead of `cdn.jsdelivr.net`. Kerstin then works on a LAN without internet, and the browser no longer contacts a third party on each visit (relevant for GDPR, T041).

## Context
- `frontend/index.html:9-10` loads `onnxruntime-web@1.14.0/dist/ort.js` and `@ricky0123/vad-web@0.0.22/dist/bundle.min.js` from jsDelivr.
- `frontend/app.js` (`vad.MicVAD.new`) sets `baseAssetPath` and `onnxWASMBasePath` to jsDelivr URLs. From there the library fetches the worklet, the Silero `.onnx` model and the `ort-wasm*.wasm` files.
- Licenses are already cleared in `docs/LICENSES.md`: vad-web ISC, onnxruntime-web MIT, Silero VAD MIT. Both licenses require shipping the license text with the files.
- The pattern to follow is `scripts/get_voice.sh` + `make voice`: large binaries are downloaded by a script and gitignored (`voices/*.onnx`).
- **Versions stay exactly as they are** (vad-web 0.0.22, onnxruntime-web 1.14.0). This task is only about where the files come from. No behaviour change.

## Spec
1. **Find the real file list first.** Load the current page (port 8771) in headless Chromium, start a session, and log every request to `cdn.jsdelivr.net`. The vendored set is exactly those files plus each package's `LICENSE`. Paste the list (path, size) in the report. Don't guess from the package listing: list only what the page actually fetches, plus the license files.
2. **`scripts/get_frontend_vendor.sh`** (bash, `set -euo pipefail`, same style as `get_voice.sh`):
   - Download the **npm registry tarballs** (`https://registry.npmjs.org/<pkg>/-/<name>-<ver>.tgz`) for both packages.
   - Verify each tarball against a **pinned SHA-512** hard-coded in the script (taken from the registry's `dist.integrity`). On a mismatch: delete the file, print an error, exit 1.
   - Extract only the needed files (from step 1) into `frontend/vendor/vad-web/` and `frontend/vendor/onnxruntime-web/`, plus `LICENSE` into each.
   - Idempotent: skip a package whose files are all present. `--force` re-downloads.
   - Use `curl` and `tar` only; no `npm`/`node` needed.
3. **Makefile:** a `vendor` target (`## download pinned browser VAD/ONNX assets into frontend/vendor`). Mention it in the `setup` help text. Don't make `setup` download it implicitly.
4. **`.gitignore`:** `frontend/vendor/` (the tarballs and extracted files are not committed).
5. **Frontend:**
   - `index.html`: `vendor/onnxruntime-web/ort.js` and `vendor/vad-web/bundle.min.js` (relative paths).
   - `app.js`: `baseAssetPath: "vendor/vad-web/"`, `onnxWASMBasePath: "vendor/onnxruntime-web/"`.
   - No CDN URL is left anywhere in `frontend/`.
   - If `window.vad` is undefined at start (vendor files missing), show the state „Fehlende Dateien – bitte ‚make vendor‘ ausführen“ and don't throw.
6. **Server visibility:**
   - `/health` gains `"frontend_vendor": true|false`: true if all files from step 1 exist under `settings.frontend_dir / "vendor"`. The file list is one constant in `main.py` (or a small module).
   - `scripts/check_env.sh` gains a "Frontend" section: `[ok] vendor assets` or `[FAIL] vendor assets missing -> make vendor`.
7. **Static serving:** check that StaticFiles serves `.wasm` as `application/wasm` and `.onnx` with some binary type. If `.wasm` doesn't come back as `application/wasm`, register the MIME type (`mimetypes.add_type`) in `main.py`. Show the `curl -sI` headers in the report.
8. **Docs:**
   - `README.md` setup steps: add `make vendor`.
   - `docs/LICENSES.md`: a note under the three rows that the files are shipped from `frontend/vendor/` with their license files.
   - `docs/ARCHITECTURE.md` (if it mentions the CDN): update it.
9. **Tests:**
   - `/health` reports `frontend_vendor` false for an empty temp frontend dir and true when the listed files exist (create empty placeholder files in a tmp dir; don't download in tests);
   - a test that `frontend/index.html` and `frontend/app.js` contain no `http://` or `https://` asset URL (whitelist: none).

## Files allowed to change
- `scripts/get_frontend_vendor.sh` (new), `Makefile`, `.gitignore`
- `frontend/index.html`, `frontend/app.js`
- `backend/kerstin/main.py` (the `/health` field, the constant, the MIME type if needed)
- `scripts/check_env.sh`
- `backend/tests/test_vendor.py` (new)
- `README.md`, `docs/LICENSES.md`, `docs/ARCHITECTURE.md`, `docs/STATUS.md` (one line), this task file

## Out of scope
- Upgrading vad-web or onnxruntime-web, or changing VAD parameters.
- Committing any vendored binary to git.
- Service worker / offline caching.
- Anything on other services. This task touches no GPU and no Ollama.

## Acceptance criteria
- [x] `make test` and `make lint` pass.
- [x] `make vendor` on a clean checkout downloads, verifies and extracts. A second run is a no-op. A corrupted tarball (simulate by editing a pinned hash in a scratch copy) fails with exit 1 and leaves no partial files.
- [x] `grep -rn "jsdelivr\|unpkg\|https://" frontend/*.html frontend/*.js` → no hits.
- [x] Headless Chromium on port 8771: a session starts and VAD initialises **with outbound network to jsDelivr blocked** (e.g. Chromium `--host-resolver-rules="MAP cdn.jsdelivr.net 0.0.0.0"`). The network log shows only same-origin requests. Paste the log.
- [x] `curl -s https://localhost:8771/health -k | jq .frontend_vendor` → `true`, and `false` after temporarily moving `frontend/vendor` away.
- [x] `make check` shows the Frontend line.
- [x] Worker report filled in. No new dependencies (curl/tar only).

## Worker report (Kilo Code fills this in)
- **Changed files:** `scripts/get_frontend_vendor.sh` (new), `Makefile`, `.gitignore`, `frontend/index.html`, `frontend/app.js`, `backend/kerstin/main.py`, `scripts/check_env.sh`, `backend/tests/test_vendor.py` (new), `README.md`, `docs/LICENSES.md`, `docs/ARCHITECTURE.md`, `docs/STATUS.md`, this task file.
- **How tested:** `make test` → 253 Python tests + 33 Node tests passed; `make lint` → ruff passed. `make vendor` downloaded and extracted the pinned assets; the second run printed both `exists` lines and did not download. A scratch copy with an edited vad-web SHA-512 exited 1 with `ERROR: SHA-512 mismatch for vad-web-0.0.22` and left no `frontend/vendor` directory. `grep -rn "jsdelivr\|unpkg\|https://" frontend/*.html frontend/*.js` has no hits. The blocked Chromium run logged only same-origin requests, loaded the worklet from `/vendor/vad-web/`, and `window.vad` was an object with state `hört zu …`. `/health` returned `true`, then `false` with `frontend/vendor` moved away, then `true` after restore. `make check` printed `[ok] vendor assets`. The `.wasm` response is `application/wasm`; the `.onnx` response is `application/octet-stream`.
- **Page request log (unblocked, port 8771):**
  - `/npm/onnxruntime-web@1.14.0/dist/ort.js` — 507,289 bytes, `application/javascript`
  - `/npm/@ricky0123/vad-web@0.0.22/dist/bundle.min.js` — 5,115 bytes, `application/javascript`
  - `/npm/@ricky0123/vad-web@0.0.22/dist/vad.worklet.bundle.min.js` — 2,585 bytes, `application/javascript` (the AudioWorklet fetch is delayed past the initial page capture)
  - `/npm/@ricky0123/vad-web@0.0.22/dist/silero_vad_legacy.onnx` — 721,513 bytes, `application/octet-stream`
  - `/npm/onnxruntime-web@1.14.0/dist/ort-wasm-simd.wasm` — 1,814,356 bytes, `application/wasm`
  - Plus `vad-web/LICENSE` (1,896 bytes) and `onnxruntime-web/LICENSE` (1,073 bytes). The HTTP sizes above are transfer sizes; installed files are larger because the tarballs are compressed (e.g. `ort.js` 3,966,081 bytes, `ort-wasm-simd.wasm` 10,014,674 bytes on disk).
- **Blocked Chromium network log** (`--host-resolver-rules="MAP cdn.jsdelivr.net 0.0.0.0"`):
```text
click: clicked
page: {"vad":"object","state":"hört zu …","startDisabled":true}

ALL_REQUESTS
https://localhost:8771/	status=200	mime=text/html	size=4380	host=localhost
https://localhost:8771/style.css	status=200	mime=text/css	size=6675	host=localhost
https://localhost:8771/vendor/onnxruntime-web/ort.js	status=200	mime=text/javascript	size=3966335	host=localhost
https://localhost:8771/vendor/vad-web/bundle.min.js	status=200	mime=text/javascript	size=19343	host=localhost
https://localhost:8771/mic_gate.js	status=200	mime=text/javascript	size=2909	host=localhost
https://localhost:8771/exam_ui.js	status=200	mime=text/javascript	size=2140	host=localhost
https://localhost:8771/markdown.js	status=200	mime=text/javascript	size=9346	host=localhost
https://localhost:8771/app.js	status=200	mime=text/javascript	size=27638	host=localhost
https://localhost:8771/api/scenarios	status=200	mime=application/json	size=395	host=localhost
https://localhost:8771/api/mistakes	status=200	mime=application/json	size=170	host=localhost
https://localhost:8771/api/exams	status=200	mime=application/json	size=444	host=localhost
https://localhost:8771/favicon.ico	status=404	mime=application/json	size=154	host=localhost
https://localhost:8771/vendor/vad-web/silero_vad_legacy.onnx	status=200	mime=application/octet-stream	size=1807770	host=localhost
https://localhost:8771/vendor/onnxruntime-web/ort-wasm-simd.wasm	status=200	mime=application/wasm	size=10014915	host=localhost

EXTERNAL_REQUESTS
(none)

CDN_REQUESTS
```
- The AudioWorklet fetch is not exposed as a page request by CDP, but the same blocked run's server access log shows it loading from the vendor directory:
```text
INFO:     127.0.0.1:59442 - "GET /vendor/vad-web/vad.worklet.bundle.min.js HTTP/1.1" 200 OK
```
- **MIME and health headers:**
```text
HTTP/1.1 200 OK
content-type: application/wasm
content-length: 10014674

HTTP/1.1 200 OK
content-type: application/octet-stream
content-length: 1807522

$ curl -sk https://localhost:8771/health | jq .frontend_vendor
true
false  # after temporarily moving frontend/vendor away
true   # after restoring it
```
- **Measurements (if any):** Vendor download sizes: vad-web tarball 3.4 MB, onnxruntime-web tarball 15.8 MB; installed vendor directory contains the four page files plus two licenses. No latency/GPU changes.
- **Deviations from spec / extra files touched:** The npm tarballs for these pinned versions do not contain a `LICENSE` file. The script therefore fetches the upstream license texts (vad-web at the package's `gitHead`, onnxruntime-web at `v1.14.0`) into each vendor directory. No binaries are committed; `frontend/vendor/` is gitignored. The pre-existing `.gitignore` `*.prs` change is still present but not staged.
- **New dependencies (+license):** None. The script uses `curl`, `tar` and the standard `openssl`/`base64` utilities for SHA-512 verification; no npm or node.
- **Open questions:** None.

## Review (Claude Code fills this in)
- **Verdict:**
- **Notes:**
