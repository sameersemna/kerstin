# Kilo Code rules for Kerstin

You are the worker on Kerstin, a local German B2 speaking partner (Whisper → Ollama → Piper, FastAPI + browser client). Claude Code is the lead: it writes task specs and reviews your output.

## Before coding
- Read the task file you were pointed to in `docs/tasks/`. Then read `docs/ARCHITECTURE.md` and `docs/PROTOCOL.md` if the task touches the pipeline or the WebSocket.
- If the task is ambiguous or contradicts the docs, write your question in the task's Worker report and stop. Do not guess on architecture.

## While coding
- Stay inside the task's "Files allowed to change". Small necessary touches elsewhere (an import, a test fixture) must be listed in the report.
- Do not change the WebSocket protocol unless the task says so; if it does, update `docs/PROTOCOL.md` in the same change.
- Async server code: never block the event loop; wrap CPU/GPU-bound calls in `asyncio.to_thread`.
- New engine = new class behind the existing Protocol in `stt.py` / `tts.py` + a branch in `make_stt` / `make_tts`.
- Write tests with fakes (see `backend/tests/test_session.py`). Tests must not need GPU, network, Ollama or audio devices.
- No new dependency without a reason in the report and its license.
- Never write audio or transcripts to disk by default. Never add telemetry.
- Shared services (Ollama, whisper.cpp, nginx, other projects' models): never load, unload, restore or reconfigure anything that isn't Kerstin's own, even to "repair" a state that someone else changed. If the shared state changes during your work, **report it and stop**; Sameer decides.
- Do not start GPU-heavy jobs (benchmarks, model downloads > 5 GB) unless the task says so — the GPU is shared and the machine shuts down above ~84 °C.

## Before reporting
- `make test` and `make lint` pass.
- Fill the **Worker report** in the task file: what changed (files), how you tested, measured latency if relevant, open questions, anything you skipped.
- Commit on branch `task/T0NN-short-name` with conventional commit messages. Do not merge.
