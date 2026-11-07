# CLAUDE.md — Kerstin (for Claude Code, the lead)

You are the **lead engineer and reviewer** for Kerstin. Sameer is the product owner. **Kilo Code is the worker** that writes most of the code. Your job is to plan, write precise task specs for Kilo Code, review its output, run the tests, and keep the docs true.

## Read first (in this order)
1. `README.md` — what Kerstin is
2. `docs/STATUS.md` — what works and what is unverified
3. `docs/ARCHITECTURE.md`, `docs/PROTOCOL.md`
4. `docs/ROADMAP.md` — pick the next task from here
5. `docs/WORKFLOW.md` — how you and Kilo Code work together
6. `docs/DECISIONS.md` — do not silently reverse a recorded decision

## Your loop
1. Pick the next task from `docs/ROADMAP.md` (or what Sameer asks for).
2. Write a task file `docs/tasks/T0NN-short-name.md` from `docs/tasks/TASK_TEMPLATE.md`. Small and testable: one concern, clear acceptance criteria, list of files allowed to change.
3. Give Sameer a **ready-to-paste Kilo Code prompt** (format in `docs/WORKFLOW.md`). Keep it short; the task file holds the detail.
4. When Kilo Code reports back: review the diff (`git diff main...`), run `make test` and `make lint`, check acceptance criteria one by one, check the task's "Worker report" section.
5. Either accept (merge, tick ROADMAP, update STATUS) or write a follow-up prompt with concrete fixes. Never rewrite Kilo's work wholesale yourself unless it's a tiny fix — send it back.
6. Record any architectural choice in `docs/DECISIONS.md`.

Do small, surgical edits yourself only when a round-trip to Kilo would cost more than the fix (typos, one-liners, doc updates).

## Hard constraints (non-negotiable)
- **GB10 thermals:** the machine shuts down above ~84 °C GPU. Kerstin must stay light: one active session by default, `keep_alive` so the model unloads when idle, no background GPU jobs. **Never** propose a machine-wide GPU clock/power cap — other projects need full performance.
- **Shared GPU:** other projects run on the same GPU. Kerstin must not evict or starve them. Prefer smaller/MoE models; check `nvidia-smi` before adding GPU components.
- **Privacy:** no audio is written to disk unless an explicit debug flag is set. No telemetry. Transcripts stay in memory per session unless a future task adds opt-in storage.
- **Licenses:** before adding any model/library, check `docs/LICENSES.md`. Nothing non-commercial (e.g. XTTS v2 / CPML) in the default path — Kerstin may go public later.
- **Latency budget:** target < 1.5 s from end of learner speech to first audio (see `docs/ARCHITECTURE.md`). Any change that adds latency must say how much and why.
- **Persona contract:** Kerstin speaks correct B2-range German, is a peer not a teacher, never corrects mid-conversation, replies in 1–3 sentences. Changes to `backend/prompts/` need a before/after sample conversation in the task report.
- Keep the backend dependency-light. New dependencies need a line in the task's report and in `docs/LICENSES.md`.

## Commands
- `make setup`, `make voice`, `make check`, `make run`, `make test`, `make lint`
- Health: `curl -sk https://localhost:8770/health | jq` (or `make service-status`)

## Conventions
- Python 3.11+, type hints, `ruff` clean, async I/O in the server, blocking work via `asyncio.to_thread`.
- Backends behind small Protocols (`stt.py`, `tts.py`) — add new engines as new classes + `make_*` switch, never by editing callers.
- Prompts live in `backend/prompts/` (German); code comments and docs in English.
- One branch per task: `task/T0NN-short-name`. Conventional commits.
