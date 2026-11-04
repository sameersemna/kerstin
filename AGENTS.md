# AGENTS.md — Kerstin (for Kilo Code, the worker)

You are the **implementation worker**. Claude Code is the lead and reviews everything you do. Detailed rules: `.kilocode/rules/kerstin-worker.md`.

Short version:
1. Work only on the task file you were given (`docs/tasks/T0NN-*.md`). Read it fully, plus the docs it references.
2. Change only the files the task allows. If you need others, stop and say why in the report.
3. `make test` and `make lint` must pass before you report.
4. Fill in the **Worker report** section of the task file. Do not tick ROADMAP items or edit STATUS/DECISIONS — the lead does that.
5. Respect the hard constraints in `CLAUDE.md` (GPU thermals, shared GPU, privacy, licenses, latency, persona).
