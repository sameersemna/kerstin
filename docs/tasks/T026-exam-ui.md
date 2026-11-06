# T026 — Exam UI

**Branch:** `task/T026-exam-ui` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
Sameer can pick an exam preset in the browser and go through a full practice exam: see the part, the task card and a countdown, press „Fertig“/„Weiter“ to move on, and get feedback at the end. Free conversation works exactly as before.

## Context
- The backend is done (T021, D021). See `docs/PROTOCOL.md`:
  - `start.exam` and `exam_next`;
  - `session.exam` carries `{preset,title,note,parts:[{kind,title,seconds}]}`;
  - the server sends `exam_part` with `index,kind,title,seconds,ui_text,card` (or `kind:"done"`), plus `collected`.
- The server starts Kerstin turns on its own (part openers, her talk, the follow-up after the learner's talk). Each one increments the server turn id **without** a learner utterance. Today the client moves `currentTurn` forward only on `transcript`, on `reply_text`, and on its own utterances.
- Card shapes (`backend/prompts/exam.json`):
  - talk: `{title, points[]}`;
  - discussion: `{question, aspects[]}`;
  - planning: `{situation, points[]}`;
  - Kerstin's talk: `{title}` only.
- **Gap found while writing this task:** in the `prep` part, the server still transcribes speech and Kerstin replies normally. A candidate doesn't speak during preparation, and STT runs on the shared GPU for nothing.

## Spec
1. **`GET /api/exams`** (`main.py`): returns `[{"key","title","note"}]` from `load_presets(settings.prompts_dir)["presets"]`, in file order. If the file fails to load, return `[]` and log a warning. Never return a 500.
2. **Prep guard** (`session.py`): if an exam is active and the current part is `prep`:
   - drop the utterance **before STT**;
   - send `{"type":"stt_empty","turn","reason":"prep"}`;
   - keep turn ids in sync, the same way as the other early returns.

   Document `reason:"prep"` in `PROTOCOL.md`.
3. **Pure logic module `frontend/exam_ui.js`** (no DOM, testable with `node --test`, loaded like `mic_gate.js`). It exports:
   - `cardLines(kind, card)` → `{heading, items[]}`:
     - talk cards → title + points;
     - discussion → question + aspects;
     - planning → situation + points;
     - `kerstin_talk` → title + no items;
     - `null` → `null`.
   - `nextButton(state)` → `{label, enabled}`, where `state = {kind, isLast, followupSent}`:
     - prep → „Ich bin bereit“;
     - learner_talk before the follow-up → „Fertig“;
     - learner_talk after the follow-up, kerstin_talk, dialog → „Weiter“;
     - the last part (after its follow-up, if any) → „Prüfung beenden“;
     - `done` → disabled.
   - `autoAction(kind, elapsedS, seconds, followupSent)` → `"advance" | "finish_talk" | null`:
     - prep at `elapsed ≥ seconds` → `"advance"`;
     - learner_talk at `elapsed ≥ seconds + 30` and no follow-up sent yet → `"finish_talk"`;
     - otherwise `null`. Kerstin's talk and dialog parts never auto-advance.
   - `formatClock(remainingS)` → `"m:ss"`; at ≤ 0 → `"Zeit um"`.
4. **UI** (`index.html`, `app.js`, `style.css`):
   - **Mode select `#mode`:** „Freies Gespräch“ plus one option per preset from `/api/exams`.
     - With an exam selected: `start` sends `exam:<key>`; the start button reads „Prüfung starten“; `#scenario` and `#useFocus` are disabled (the server ignores focus in exam mode).
     - With „Freies Gespräch“ selected: everything behaves exactly as today.
   - **Exam panel `#examPanel`** (hidden outside exam mode), shown above the log:
     - preset title + `note` in small text (it's the "not an official exam" disclaimer, so keep it visible);
     - „Teil N von M – {title}“;
     - `ui_text`;
     - the card (heading + bullet list, built with `textContent`/`createElement` only, no `innerHTML`);
     - a countdown (`formatClock`, ticking once per second, restarting on each `exam_part`);
     - one button `#examNextBtn` with its label from `nextButton`.
   - **The button:**
     - sends `{"type":"exam_next"}`;
     - in learner_talk the first press sets `followupSent`;
     - it is disabled for 1 s after each press (no double advance);
     - `autoAction` runs on each tick and does the same as a press.
   - **Done:** on `exam_part kind:"done"`, the panel shows „Prüfung beendet – hol dir jetzt dein Feedback.“ The timer stops and „Beenden & Feedback“ is enabled.
   - **Prep:**
     - the client doesn't send utterances during `prep` (don't increment `currentTurn`, don't send);
     - the state line shows „Vorbereitung – Mikrofon aus“;
     - the server guard (step 2) is the safety net.
   - **Learner talk:** on `collected`, call `micGate.replyFinished(msg.turn)` and show „Kerstin hört zu …“.
   - **Turn sync:** when any server message carries `turn > currentTurn` (`status`, `reply_text`, `collected`, `stt_empty`), move `currentTurn` up to it. Audio for server-started turns must play, and the speaker-mode mic gate must pause during it and resume after `reply_done`, the same as for a normal reply.
   - **Session reset:** a new `session` message (any mode) clears the panel, the timer and `followupSent`.
5. **Tests:**
   - `frontend/tests/exam_ui.test.js`: every branch of `cardLines`, `nextButton`, `autoAction` and `formatClock`.
   - Python:
     - `/api/exams` lists both presets and returns `[]` when the file is missing;
     - prep guard: an utterance in `prep` → `stt_empty` with reason `prep`, the fake STT is not called, and the turn id still increments;
     - an utterance after `exam_next` (in `learner_talk`) → `collected`.
6. **Manual run (Kilo, port 8771):** start each preset once in the browser if available. Otherwise, run a headless WebSocket script that walks through every part with `exam_next` and confirms the message sequence. Paste the sequence. Sameer does the real voice run.

## Files allowed to change
- `backend/kerstin/main.py` (`/api/exams` only)
- `backend/kerstin/session.py` (prep guard only)
- `frontend/exam_ui.js` (new), `frontend/app.js`, `frontend/index.html`, `frontend/style.css`
- `frontend/tests/exam_ui.test.js` (new)
- `backend/tests/test_exam.py`, `backend/tests/test_api_exams.py` (new, modelled on `test_api_mistakes.py`)
- `docs/PROTOCOL.md`, this task file

## Out of scope
- Any prompt file (`backend/prompts/`), the exam cards, markers or the eval.
- Scoring/rubric (T025).
- Changes to the feedback prompt or to feedback in exam mode (it runs as is on the exam transcript).
- The hint box and the mistake log stay as they are (both still work in exam mode).

## Acceptance criteria
- [ ] `make test` and `make lint` pass. Node tests include `exam_ui.test.js`.
- [ ] `curl -s localhost:8771/api/exams | jq` lists `praesentation_diskussion_planung` and `vortrag_diskussion` with title and note.
- [ ] Prep-guard test: no STT call in `prep`, `stt_empty` reason `prep`, turn ids stay in sync.
- [ ] With „Freies Gespräch“, the start message and the UI are unchanged (diff check: no exam fields are sent).
- [ ] The card is rendered without `innerHTML` (`grep -n innerHTML frontend/app.js` shows no new hits).
- [ ] The pasted walk-through covers both presets, every part in order, and ends with `exam_part kind:"done"`.
- [ ] Worker report filled in. No new dependencies.

## Worker report (Kilo Code fills this in)
- **Changed files:** `backend/kerstin/main.py` (`GET /api/exams`), `backend/kerstin/session.py` (prep guard), `frontend/exam_ui.js` (new), `frontend/app.js`, `frontend/index.html`, `frontend/style.css`, `frontend/tests/exam_ui.test.js` (new), `backend/tests/test_exam.py`, `backend/tests/test_api_exams.py` (new), `docs/PROTOCOL.md`.
- **How tested:** `make test` → 234 Python tests + 33 Node tests passed; `make lint` → ruff passed. `node --test frontend/tests/exam_ui.test.js` → 10 passed. `/api/exams` on `127.0.0.1:8771` returns both presets with title and note. Headless Chromium loaded the page and populated both exam options; `#examPanel` stayed hidden before start. Headless WebSocket walkthrough (port 8771, `KERSTIN_TTS_BACKEND=none`, `KERSTIN_LLM_WARMUP=false`, configured `qwen3:14b`):
  - `praesentation_diskussion_planung`: session (prep, learner_talk, kerstin_talk, dialog, dialog) → greeting `reply_done` → exam_part 0 prep → 1 learner_talk → follow-up `reply_done` → 2 kerstin_talk → 3 dialog → 4 dialog → `exam_part kind:"done"`.
  - `vortrag_diskussion`: session (prep, learner_talk, kerstin_talk, dialog) → greeting `reply_done` → exam_part 0 prep → 1 learner_talk → follow-up `reply_done` → 2 kerstin_talk → 3 dialog → `exam_part kind:"done"`.
  - No errors or thermal messages. The walkthrough sent no learner audio, so it exercised the server's follow-up path but not a real `collected` turn; the `collected` UI path is covered by the server test and the pure-logic tests.
- **Measurements (if any):** No UI latency benchmark. GPU stayed 51–56 °C during the walkthrough; `qwen3:14b` loaded (~9.8 GB VRAM) and was left to its configured keep-alive. `grep -n innerHTML frontend/app.js` shows only the three pre-existing hits (no new card/option rendering).
- **Deviations from spec / extra files touched:** None. The pre-existing `.gitignore` change was left untouched and is not staged. The temporary walkthrough script lives in `/tmp/kilo`, not the repo.
- **New dependencies (+license):** None.
- **Open questions:** Sameer still needs the real voice run. The headless walkthrough used `qwen3:14b` with TTS disabled, so it validates protocol/part sequencing, not speech or the browser audio/mic gate.

## Review (Claude Code fills this in)
- **Verdict:**
- **Notes:**
- **Verdict:** Accepted. Merged to main after one lead fix.
- **Notes:**
  - The diff matches the spec:
    - `/api/exams` never returns a 500;
    - the prep guard runs before STT;
    - `exam_ui.js` is pure and fully tested;
    - the card is built with `createElement`/`textContent`;
    - the free-conversation start payload is unchanged (`exam` is added only when a preset is selected);
    - turn sync is centralised in `syncTurn`;
    - `collected` releases the mic gate.

    234 Python + 33 Node tests pass, and lint passes.
  - **Lead fix:** `examBlocksSpeech()` used `examSession || modeEl.value`. Changing the mode select during a running free conversation would have muted the learner. Now only an active exam session blocks speech.
  - **Known, accepted:** pressing „Weiter“ while Kerstin speaks stops playback, and the server interrupts. Audio frames already in flight for that turn could still play briefly; normal interrupts behave the same way.
  - **Not verified:** real audio, the speaker-mode mic gate on server-started turns, and the 30 s auto-finish. These need Sameer's voice run.
  - The walkthrough used the `.env` model (`qwen3:14b`), not the default `gemma4:26b`.
