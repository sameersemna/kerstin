# T014 — Echo handling: speaker mode, interrupt button, server-side echo filter

**Branch:** `task/T014-echo-handling` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
Kerstin works **without headphones**. With laptop speakers today, Kerstin's own voice reaches the mic: VAD fires, the browser treats it as barge-in, cuts her off, and sends her own words as a learner turn, so she may answer herself. After this task:
- **Lautsprecher-Modus** (new default): the mic is paused while Kerstin speaks, and the learner interrupts with a button or the space bar.
- **Kopfhörer-Modus**: today's voice barge-in, unchanged.
- **Server echo filter** (both modes): a transcript that is mostly Kerstin's own last reply is dropped as `echo`.

## Context
- `frontend/app.js`:
  - `vad.MicVAD` runs all the time;
  - `onSpeechStart` while audio plays → `stopPlayback()` + `{"type":"interrupt"}`;
  - `onSpeechEnd` → `currentTurn += 1` + send PCM.
  - Playback queue: `playQueue`, `playing`, `playNext()`.
  - `vadInstance.pause()` / `.start()` exist in vad-web 0.0.22.
- Server: `Session._turn` filters transcripts (T013, `stt_filter.py`), and `stt_empty` has a `reason`. `history` holds Kerstin's replies as `assistant` messages.
- The browser's built-in echo cancellation doesn't reliably cancel Web Audio playback, so don't rely on it.
- No JS test setup exists. Node 24 is installed on the GB10, so use the **built-in `node --test`, with no npm and no dependencies**.

## Spec
1. **Mic gate module** (`frontend/mic_gate.js`, new): a plain script with no imports.
   - It defines `createMicGate({ mode, tailMs, pauseVad, resumeVad, setTimer, clearTimer })` and exposes it as `globalThis.createMicGate`, plus `module.exports` when `module` exists, so Node can `require` it.
   - Events:
     - `playbackStarted()`
     - `replyFinished()` (on `reply_done`, `reply_interrupted`, `error`, or `stt_empty` while paused)
     - `playbackIdle()` (queue empty, nothing playing)
     - `userInterrupt()`
     - `setMode(mode)`
   - Rules:
     - **speakers:** `playbackStarted` → `pauseVad()` (once; idempotent). Resume (`resumeVad()`) only when **both** `replyFinished` and `playbackIdle` have happened for the current reply, plus `tailMs` (default 350 ms, for room echo) via the injected timer. A new `playbackStarted` during the tail cancels the timer. `userInterrupt` resumes immediately (no tail).
     - **headphones:** never pauses; all events are no-ops except `userInterrupt`.
     - `setMode` while paused in headphones mode → resume immediately.
   - Expose `isListening()` for the UI.
2. **Wire into `app.js`:**
   - Create the gate after `MicVAD.new`, with `pauseVad: () => vadInstance.pause()` and `resumeVad: () => vadInstance.start()`.
   - Call `playbackStarted` in `playNext` when a source starts, `playbackIdle` when the queue drains, and `replyFinished` on the messages listed above.
   - **Interrupt action** (button + space bar when focus isn't in a form control): `stopPlayback()`, send `interrupt`, `gate.userInterrupt()`. Works in both modes.
   - In **speakers** mode, `onSpeechStart` must not barge in. That should already hold because VAD is paused, but guard it too: only barge in when `gate` mode is headphones.
   - State text: "Kerstin spricht … (Leertaste = unterbrechen)" while paused in speakers mode.
3. **UI** (`frontend/index.html`, `frontend/style.css`):
   - A `<select id="micMode">` with "Lautsprecher (Mikro pausiert, während Kerstin spricht)" and "Kopfhörer (einfach dazwischenreden)". **Default: Lautsprecher.**
   - Remember the choice in `localStorage` (wrap it in try/catch).
   - A button `id="interruptBtn"` "Unterbrechen", enabled only while Kerstin is speaking.
   - Include `mic_gate.js` before `app.js`. Minimal styling, consistent with the existing CSS.
4. **Server echo filter** (`backend/kerstin/stt_filter.py`, `session.py`):
   - Add `is_echo(transcript: str, last_reply: str, min_words: int = 4, threshold: float = 0.7) -> bool`. It's True when the normalized transcript has ≥ `min_words` words and `difflib.SequenceMatcher` on the word lists gives ratio ≥ `threshold` against the last reply, **or** the transcript's words appear as a contiguous run (≥ `min_words`) inside the last reply.
   - In `_turn`, after `clean_transcript`, with `stt_filter` on: compare against the most recent `assistant` message in `history`. Echo → `stt_empty` with `reason: "echo"`. Don't touch history and don't call the LLM. Log the reason only, never the text.
   - Add `echo` to the `stt_empty` reasons in `docs/PROTOCOL.md`. No other protocol change.
5. **Tests:**
   - `frontend/tests/mic_gate.test.js` (`node:test` + `node:assert`, fake timer):
     - (a) speakers: pause on start; no resume until both reply-finished and idle, then after the tail;
     - (b) a new playback during the tail cancels the resume;
     - (c) `userInterrupt` resumes immediately;
     - (d) headphones never pauses;
     - (e) switching mode while paused resumes;
     - (f) `pauseVad` is called only once per reply.
   - `backend/tests/test_stt_filter.py`:
     - an exact echo, a partial echo (≥ 4 words contiguous) and an echo with STT punctuation differences → True;
     - a learner answer that shares 1–2 words with the reply → False;
     - a short "Ja, genau." → False;
     - an empty last reply → False.
   - `backend/tests/test_session.py`: an STT fake that returns Kerstin's opener text → `stt_empty`/`echo`, with history and LLM untouched.
   - **Makefile:** `test-js: ## frontend unit tests (node --test, no deps)` → `node --test frontend/tests/`. `make test` runs it too when `node` is on PATH, and prints "skip JS tests (no node)" otherwise, so it still passes without Node.
6. **README:** replace "Use headphones …" with two lines: speaker mode (default) vs headphone mode, plus the space-bar interrupt.

## Hard rules
No new dependencies (no npm, no packages). No change to vad-web/onnxruntime versions or CDN URLs (that's T003). If you run a server, use port 8771; leave 8770 alone. No audio on disk. No transcript text in INFO logs.

## Files allowed to change
- `frontend/mic_gate.js` (new), `frontend/tests/mic_gate.test.js` (new), `frontend/app.js`, `frontend/index.html`, `frontend/style.css`
- `backend/kerstin/stt_filter.py`, `backend/kerstin/session.py` (`_turn` echo check only)
- `backend/tests/test_stt_filter.py`, `backend/tests/test_session.py`
- `docs/PROTOCOL.md` (`stt_empty` reasons only), `Makefile`, `README.md` (headphones line only)
- this task file (Worker report only)

This is 12 files, over the usual 8. The server part is small and is the safety net for the frontend part, so it stays in one task (lead-approved).

## Out of scope
Changing VAD thresholds or `redemptionFrames` (D012), vendoring assets (T003), WebRTC AEC tricks, server-side VAD, and any LLM/persona change.

## Acceptance criteria
- [ ] `make test` (Python + JS) and `make lint` pass; `node --test frontend/tests/` → all of (a)–(f) pass
- [ ] Echo tests pass; the session echo test shows no LLM call and no history change
- [ ] `make smoke` still passes (headless; mode-independent)
- [ ] In the code, speakers mode cannot trigger a voice barge-in (`onSpeechStart` guard + paused VAD), and headphones mode behaves exactly as before
- [ ] The mode persists across reloads (localStorage, try/catch); the interrupt button and space bar work in both modes
- [ ] `git diff main --stat` shows only allowed files

## Manual check (Sameer, after merge, **without headphones**)
1. Speaker mode: talk normally for 2 minutes. Kerstin must never cut herself off or answer her own words.
2. Press space while she talks: she stops at once, and the mic listens again.
3. Switch to headphone mode, put headphones on: talking over Kerstin interrupts her, as before.

## Worker report (Kilo Code fills this in)
- **Changed files:**
- **How tested:**
- **Measurements (if any):**
- **Deviations from spec / extra files touched:**
- **New dependencies (+license):**
- **Open questions:**

## Review (Claude Code fills this in)
- **Verdict:**
- **Notes:**
