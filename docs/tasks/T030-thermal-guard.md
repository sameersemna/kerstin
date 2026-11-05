# T030 — Runtime thermal guard

**Branch:** `task/T030-thermal-guard` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
When the GB10 GPU is hot (from Kerstin or from other projects), Kerstin stops adding GPU load: she doesn't start new sessions, transcribe new turns, run warm-ups or generate feedback until the GPU has cooled down. She tells the learner in the UI instead of failing silently. She never touches clocks, power limits, or other projects' processes (D016).

## Context
- The machine shuts down at ≈84 °C GPU, and the GPU is shared. The scripts already have a guard (`scripts/smoke_test.py`: `gpu_temperature()`, abort at 80 °C), but the running server has none.
- `nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits` takes ≈18 ms on the GB10 and prints e.g. `47`.
- Kerstin's GPU work happens per turn: STT (shared whisper.cpp), the LLM (Ollama), the warm-up on `start`, and feedback (≤ 1200 tokens, the longest single job). Piper TTS runs on the CPU.
- `Session` (`backend/kerstin/session.py`): `start()`, `_turn()`, `feedback()`; `Deps` dataclass; tests use fakes via `make_session()` in `backend/tests/test_session.py`.

## Spec
1. **`backend/kerstin/thermal.py` (new)**
   - `class ThermalGuard` with `__init__(self, hot_c: float, resume_c: float, max_age_s: float = 2.0, read_temp: Callable[[], Awaitable[float | None]] | None = None, clock: Callable[[], float] = time.monotonic)`.
   - Default `read_temp` runs `nvidia-smi` via `asyncio.create_subprocess_exec` with a 2 s timeout and parses the first line as a number. On a missing binary, timeout, non-zero exit or parse error it returns `None` and logs a WARNING **once** (not on every call).
   - `async def check(self) -> ThermalStatus`. `ThermalStatus` is a small frozen dataclass: `state: Literal["ok", "hot", "unknown"]` and `temp_c: float | None`.
     - Uses a cached reading if it is younger than `max_age_s`, so there's no background task and no polling loop.
     - **Hysteresis:** the state becomes `hot` when temp ≥ `hot_c`, and stays `hot` until temp ≤ `resume_c`.
     - `None` → `unknown`, which is treated as allowed (fail-open, so a missing `nvidia-smi` never blocks Kerstin). Log state changes at INFO with the temperature only.
   - Read-only: only the temperature query. No `nvidia-smi -pl/-lgc/-rgc` or any other write flag, and no killing or unloading of processes.
2. **Config** (`config.py`, `.env.example`):
   - `thermal_guard: bool = True`
   - `thermal_hot_c: float = 80.0`
   - `thermal_resume_c: float = 74.0`

   Add a validator so that `resume_c < hot_c`.
3. **Wiring:**
   - `Deps.thermal: ThermalGuard | None = None` (None = disabled); `main.py` creates it when `thermal_guard` is on.
   - `/health` gains `"gpu_temp_c"` (number or null) and `"thermal"` (`ok|hot|unknown|disabled`).
4. **Session behaviour when `check()` returns `hot`.** Message: `{"type":"thermal","state":"hot","temp_c":<n>,"turn"?:<id>}`.
   - **`start()`:** still send `session` (the UI resets), then send `thermal` and skip both the warm-up and the opener. The opener audio is CPU-only, but without the conversation there's no point. The learner presses Start again later.
   - **`_turn()`:** check **before STT**, after the existing too-short/too-quiet gates (those are free). If hot: send `thermal` with `turn`, return, and don't change history.
   - **`feedback()`:** if hot, send `thermal` and return without calling the LLM. History is kept, so "Beenden & Feedback" works later.
   - The check runs once per turn. No mid-reply abort: a reply is short, and the 80 → 84 °C margin covers one reply.
   - Log `turn N thermal hot (gpu=82 °C)` at INFO. No transcript text.
5. **Frontend** (`frontend/app.js`), on `thermal`:
   - Show the state text `GPU zu warm (82 °C) – kurze Pause, bitte gleich nochmal versuchen`.
   - Call `micGate.replyFinished(msg.turn)` when the gate exists, the same way `stt_empty` is handled, so speaker mode can never get stuck paused.
   - If it came in reply to `start` (no `turn`), re-enable the Start button.
6. **`docs/PROTOCOL.md`:** add the `thermal` row and the two `/health` fields.
7. **Tests:**
   - **`backend/tests/test_thermal.py` (new).** Use a fake `read_temp` and a fake clock:
     - ok below `hot_c`;
     - hot at `hot_c`;
     - stays hot at 77 (between the two thresholds);
     - ok again at `resume_c`;
     - the cache is reused within `max_age_s` (count reads) and refreshed after it;
     - `None` → `unknown`, and the warning is logged only once (`caplog`);
     - the default reader parses `"47\n"`. Monkeypatch the subprocess; don't run the real `nvidia-smi` in tests.
   - **`backend/tests/test_session.py`:** with a fake hot guard:
     - a turn → a `thermal` message, STT not called, LLM not called, history unchanged;
     - `start()` → `session` + `thermal`, no opener audio, no warm-up call;
     - `feedback()` → `thermal`, no LLM call;
     - with an ok guard everything behaves as before (the existing tests pass with `thermal=None`).

## Files allowed to change
- `backend/kerstin/thermal.py` (new), `backend/kerstin/config.py`, `backend/kerstin/session.py`, `backend/kerstin/main.py`
- `backend/tests/test_thermal.py` (new), `backend/tests/test_session.py`
- `frontend/app.js` (`thermal` message only)
- `docs/PROTOCOL.md`, `.env.example`
- this task file (Worker report only)

## Out of scope
- Switching to a smaller model when hot. Loading a second model adds GPU load and memory on a shared GPU (D016).
- Any clock, power or fan setting.
- Background polling.
- Changing the scripts' own guards.
- Persisting temperature history.

## Acceptance criteria
- [ ] `make test` and `make lint` pass; the new thermal and session tests are listed above
- [ ] `grep -nE "nvidia-smi" backend/kerstin/*.py` shows only the read-only `--query-gpu=temperature.gpu` call
- [ ] With the server on port 8771 and `KERSTIN_THERMAL_HOT_C=40` (forces hot at idle; there's no real heat): `curl -sk https://localhost:8771/health | jq .thermal` → `"hot"`, and a WebSocket `start` returns `session` + `thermal` with no opener. Paste the output.
- [ ] Same with the default thresholds: `/health` shows `"ok"` and a real temperature, and `make smoke` (port 8771) passes
- [ ] Latency: state the per-turn cost of `check()` (cached vs uncached, ms); it must be ≤ 30 ms uncached
- [ ] `git diff main --stat` shows only allowed files

## Worker report (Kilo Code fills this in)
- **Changed files:** `backend/kerstin/thermal.py` (new), `backend/kerstin/config.py`, `backend/kerstin/session.py`, `backend/kerstin/main.py`, `backend/tests/test_thermal.py` (new), `backend/tests/test_session.py`, `frontend/app.js` (`thermal` message only), `docs/PROTOCOL.md`, `.env.example`, this task file.
- **How tested:** `make test` → 110 Python tests + 9 Node tests passed; `make lint` passed; `make smoke` on port 8771 with default thresholds passed both turns (turn 2: first audio 1098 ms, total 2284 ms). `grep -nE "nvidia-smi" backend/kerstin/*.py` shows only the read-only temperature query. Thermal tests use fake readers/fake clock; the default-reader test monkeypatches `asyncio.create_subprocess_exec`, so no test runs the real `nvidia-smi`.
- **Measurements (if any):** `ThermalGuard.check()`: uncached 17.39 ms/check (20 calls) and cached 0.0008 ms/check (1000 calls) on the GB10; sample 45.0 °C. This is below the 30 ms uncached limit.
  ```text
  KERSTIN_HOST=127.0.0.1 KERSTIN_PORT=8771 KERSTIN_THERMAL_HOT_C=40 KERSTIN_THERMAL_RESUME_C=30 make run

  GET /health:
  {
    "gpu_temp_c": 45.0,
    "thermal": "hot"
  }

  WS start:
  session: {"type": "session", "scenario": "freies_gespraech", "title": "Freies Gespräch"}
  thermal: {"type": "thermal", "state": "hot", "temp_c": 45.0}
  extra: none (no opener)

  Default thresholds /health:
  {
    "gpu_temp_c": 44.0,
    "thermal": "ok"
  }
  ```
- **Deviations from spec / extra files touched:** None. The forced-hot check also sets `KERSTIN_THERMAL_RESUME_C=30` because the required validator rejects `resume_c >= hot_c`.
- **New dependencies (+license):** None.
- **Open questions:** None.

## Review (Claude Code fills this in)
- **Verdict:**
- **Notes:**
