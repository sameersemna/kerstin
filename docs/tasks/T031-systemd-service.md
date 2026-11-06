# T031 — systemd user service + logs

**Branch:** `task/T031-systemd-service` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
Sameer runs `make service-install` once. Kerstin then runs as a systemd **user** service that restarts on a crash, can optionally start on boot, and logs to the journal. Nobody has to keep a terminal open for `make run`.

## Context
- Today Kerstin is started by hand: `make run` → `cd backend && ../.venv/bin/python -m kerstin` (`backend/kerstin/__main__.py`). Host, port and TLS come from `.env`. `config.py` reads `.env` by absolute path (`PROJECT_DIR / ".env"`), so the working directory doesn't matter. Environment variables override `.env` (pydantic-settings).
- The GB10 already runs **other projects' user units** in `~/.config/systemd/user/` (`gpu-thermal`, `hermes-gateway`, `ocr-server`, `openedai-gateway`, `salafi-thermald`, `sunny-brain`). They must not be touched, overwritten, restarted or reloaded beyond the `systemctl --user daemon-reload` needed for Kerstin's own unit.
- `loginctl` already shows `Linger=yes` for `sameer`, so user units can start at boot without a login. The installer only checks this and reports it. It never runs `loginctl enable-linger` (that's a system change).
- The journal is **persistent** (`/var/log/journal` exists). Log lines are therefore kept on disk. This is acceptable only because no INFO/WARNING log line contains transcript or learner text (T013 rule; checked 2026-11-06: logs carry turn ids, timings, dBFS, reasons, model names). The journald config is system-wide and shared with other projects: **do not edit it.** Rotation is journald's own size-based rotation.
- An idle Kerstin uses no GPU. The LLM warm-up runs per session during the opener, not at server start. A crash loop could still load models repeatedly if sessions reconnect, so restarts must be rate-limited.

## Spec
1. **Unit template `deploy/kerstin.service.in`** (new), with placeholders `@NAME@`, `@REPO@`, `@PORT_ENV@`:
   ```ini
   # Managed by Kerstin scripts/install_service.sh — do not edit; re-run the installer.
   [Unit]
   Description=Kerstin German conversation partner (@NAME@)
   After=network-online.target
   StartLimitIntervalSec=300
   StartLimitBurst=3

   [Service]
   Type=simple
   WorkingDirectory=@REPO@/backend
   ExecStart=@REPO@/.venv/bin/python -m kerstin
   @PORT_ENV@
   Environment=PYTHONUNBUFFERED=1
   Restart=on-failure
   RestartSec=10
   TimeoutStopSec=15
   KillSignal=SIGINT
   NoNewPrivileges=yes
   UMask=0077
   StandardOutput=journal
   StandardError=journal
   SyslogIdentifier=@NAME@

   [Install]
   WantedBy=default.target
   ```
   `@PORT_ENV@` becomes `Environment=KERSTIN_PORT=<port>` when `--port` is given, otherwise an empty line. No `EnvironmentFile`: `.env` is already read by the app.
2. **`scripts/install_service.sh`** (new, bash, `set -euo pipefail`, style of `get_voice.sh`):
   - Usage: `install_service.sh [install|uninstall|status] [--name NAME] [--port PORT] [--enable] [--dry-run]`. Defaults: `install`, name `kerstin`, no port override.
   - `--name` must match `^kerstin[a-z0-9-]*$`. Anything else exits 2. This makes it impossible to target another project's unit.
   - **install:**
     1. Check that `.venv/bin/python` exists (else: `run make setup first`, exit 1).
     2. Render the template with the absolute repo path.
     3. If `~/.config/systemd/user/<name>.service` exists and its first line is **not** the "Managed by Kerstin" marker, refuse with exit 1.
     4. Write the unit, then `systemctl --user daemon-reload`.
     5. Warn (don't fail) if the target port (from `--port`, else `KERSTIN_PORT` in `.env`, else 8770) is already listening (`ss -ltn`). Typical cause: a manual `make run`.
     6. `systemctl --user restart <name>`.
     7. With `--enable`: `systemctl --user enable <name>`, then print the linger state (`loginctl show-user "$USER" -p Linger`). If it's `no`, print the one-line hint `sudo loginctl enable-linger $USER` without running it.
     8. Print how to read logs: `journalctl --user -u <name> -f`.
   - **uninstall:**
     1. Only for a unit carrying the marker (else refuse, exit 1).
     2. `systemctl --user disable --now <name>`, remove the file, `daemon-reload`.
   - **status:** `systemctl --user status <name> --no-pager` plus `curl -sk <scheme>://localhost:<port>/health` (scheme https if `KERSTIN_TLS_CERTFILE` is set in `.env`).
   - **`--dry-run`:** print the rendered unit to stdout and the commands that would run; touch nothing (no file written, no `systemctl` call). The tests use it.
3. **Makefile:** `service-install` (`## install + start Kerstin as a systemd user service (SERVICE_ARGS="--enable" to start on boot)`), `service-uninstall`, `service-status`, `logs` (`journalctl --user -u kerstin -f`). `SERVICE_ARGS ?=` like the other `*_ARGS`. Add them to `.PHONY`.
4. **Clean shutdown:** confirm that `systemctl --user stop` (SIGINT) stops Uvicorn within `TimeoutStopSec` with no traceback in the journal while a WebSocket session is open. If Uvicorn hangs on open WebSockets, report it. Don't fix it in this task unless it's a one-liner in `__main__.py` (e.g. `timeout_graceful_shutdown=5` in `uvicorn_kwargs`), and then add a test for that kwarg.
5. **Docs:**
   - `README.md`: a short "Run as a service" section (install, enable on boot, logs, uninstall, "stop a manual `make run` first").
   - `docs/ARCHITECTURE.md`: one line under ops/deployment if such a section exists.
   - `docs/STATUS.md`: one line.
6. **Tests** `backend/tests/test_install_service.py` (new). They call the script via `subprocess` with `--dry-run` only and never run real `systemctl`:
   - default render contains `ExecStart=<repo>/.venv/bin/python -m kerstin`, `WorkingDirectory=<repo>/backend`, the marker on line 1, `Restart=on-failure`, `StartLimitBurst=3`, and no `KERSTIN_PORT`;
   - `--name kerstin-dev --port 8771` renders `Environment=KERSTIN_PORT=8771` and `SyslogIdentifier=kerstin-dev`;
   - `--name sunny-brain` and `--name ../x` exit 2;
   - no `@...@` placeholder is left in any render.
   - Skip with a clear reason if `bash` is missing.

## Files allowed to change
- `deploy/kerstin.service.in` (new), `scripts/install_service.sh` (new), `Makefile`
- `backend/kerstin/__main__.py` (only the optional one-liner from step 4) + its test
- `backend/tests/test_install_service.py` (new)
- `README.md`, `docs/ARCHITECTURE.md`, `docs/STATUS.md` (one line), this task file

## Out of scope / hard rules
- **Never install, start, stop or enable a unit named `kerstin` and never bind port 8770.** That's Sameer's. Kilo tests only with `--name kerstin-dev --port 8771`, and uninstalls it at the end.
- Never touch, restart or read the config of other users' or projects' units. No `sudo`, no `loginctl enable-linger`, no edit to `/etc/systemd/journald.conf` or any system unit.
- No log files written by Kerstin itself; no logrotate config (journald rotates).
- No change to logging content, no new dependency, no GPU/Ollama change. A short manual session for step 4 is fine (one or two turns, `cool_down()` rule, check `nvidia-smi` first and wait if another project is busy).

## Acceptance criteria
- [ ] `make test` and `make lint` pass.
- [ ] `bash scripts/install_service.sh --dry-run` prints a valid unit. `systemd-analyze --user verify` on the rendered file (written to a temp dir) shows no errors. Paste the output.
- [ ] `install --name kerstin-dev --port 8771`: the unit is active, and `curl -sk https://localhost:8771/health | jq .ok` returns `true` (or http if TLS is off). `journalctl --user -u kerstin-dev -n 20` shows the "Kerstin … ready" line. Paste both.
- [ ] Crash restart: `kill -9 <MainPID>` → the unit comes back within ~10 s (paste `systemctl --user show kerstin-dev -p NRestarts`). Four quick kills inside 5 min → the unit stays failed (start limit hit).
- [ ] Clean stop with an open WebSocket session: stops within 15 s, no traceback (paste the journal tail).
- [ ] Refusal checks: a hand-written `~/.config/systemd/user/kerstin-x.service` without the marker → install refuses (exit 1) and the file is unchanged. Delete it afterwards. `--name sunny-brain` → exit 2.
- [ ] `uninstall --name kerstin-dev` removes the unit. `ls ~/.config/systemd/user/` afterwards shows the same other-project files as before (paste before/after).
- [ ] Privacy: run `.venv/bin/python scripts/smoke_test.py --url <wss or ws>://localhost:8771/ws --turns 2` against kerstin-dev (one run only, GPU rules above), then `journalctl --user -u kerstin-dev --since "-10 min" | grep -ciE "Wochenende|Freunden|See"` → `0`. Paste the command and its output. The smoke test's known learner sentence and Kerstin's reply must not appear in the journal.
- [ ] Worker report filled in.

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
