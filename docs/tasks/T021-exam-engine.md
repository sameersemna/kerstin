# T021 — Exam training engine (B2 speaking, two presets) — server side

**Branch:** `task/T021-exam-engine` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
A session can run in **exam mode**: a sequence of timed parts modelled on two common B2 oral formats, with Kerstin as the learner's **fellow candidate** (D002 already makes her a B2 peer). This task is the **server engine, the content and a headless eval**. The UI is T026 and scoring is T025. At the end of the exam, the existing feedback runs unchanged.

## Context and design (lead, D021)
- **Presets** (data-driven, `backend/prompts/exam.json`):
  - `praesentation_diskussion_planung`, modelled on the telc-style B2 oral: presentation + questions → partner's presentation + questions → discussion → planning together;
  - `vortrag_diskussion`, modelled on the Goethe-style B2 oral: longer talk + partner question → partner's talk + question → discussion.
- **Original content only.** No official tasks, wording or brand names in prompts or UI. UI title: „B2-Prüfungstraining (Sprechen)“, with the note „angelehnt an gängige B2-Prüfungsformate – keine offizielle Prüfung“. Timings are approximate training values in `exam.json`; Sameer can adjust them after checking the free official model tests.
- **Part kinds** (generic engine, the presets only configure them):
  - `prep`: show the card, timer only, no LLM;
  - `learner_talk`: **collect mode**. Each utterance is transcribed and filtered as usual, appended to `history` as a user message, and acknowledged with `collected`. There's **no LLM call**. On `exam_next`, Kerstin asks **one** follow-up question about the talk. The learner's answer then gets one short reaction (a normal dialog turn). The next `exam_next` ends the part.
  - `kerstin_talk`: on enter, Kerstin gives her own short talk on her card (≈ `talk_words` words, using the card's points), then normal dialog: the learner asks, Kerstin answers briefly.
  - `dialog`: on enter, Kerstin opens the part in 1–2 sentences (discussion: she states a clear position; planning: she proposes a first concrete step), then normal dialog.
- **The system prompt stays fixed for the whole session** (prefix cache, T005/T024). It contains the persona + the exam addendum (`backend/prompts/exam.md`) + the chosen cards for **all** parts. Part changes are **moderation markers** in `history`: `{"role":"user","content":"[Moderation] Teil 2 – Diskussion beginnt. …"}` (constant `MODERATION_PREFIX`).
- **Persona contract:** no corrections and replies of 1–3 sentences, **except** her own talk in `kerstin_talk` (D021). No talk about scores or evaluation.

## Spec
1. **Content** (`backend/prompts/exam.json`, German, original):
   - **presets:** key, title, note, and parts `[{"kind","title","seconds","ui_text","talk_words"?}]`. Use these training values:
     - telc-style: prep 300 s, learner_talk 120 s, kerstin_talk 120 s (talk_words 130), dialog „Diskussion“ 300 s, dialog „Gemeinsam planen“ 300 s;
     - Goethe-style: prep 300 s, learner_talk 240 s, kerstin_talk 150 s (talk_words 170), dialog „Diskussion“ 300 s.
   - **pools:** `talk_topics` (≥ 8, each `title` + 4 `points`, e.g. „Situation in deinem Heimatland“, „Vor- und Nachteile“, „eigene Erfahrung“, „deine Meinung“), `kerstin_topics` (≥ 4, same shape), `discussion_questions` (≥ 6, `question` + 2 `aspects`), `planning_tasks` (≥ 6, `situation` + 4 `points`).
   - Topics are everyday B2 themes (Arbeit, Wohnen, Medien, Umwelt, Freizeit, Bildung, Gesundheit, Reisen). **The lead will check every card's German.**
2. **`backend/prompts/exam.md`** (German addendum, appended to the persona in code): the exam situation (Kerstin is a fellow candidate and nervous-but-friendly; a moderator text structures the parts), the rules per part kind as above, how to handle `[Moderation]` messages (follow them and never repeat or mention them), and the talk rule („Halte deinen Vortrag mit etwa {talk_words} Wörtern, gegliedert nach den Punkten deiner Karte, ohne Aufzählungszeichen“). Then `{cards}`, filled with all chosen cards.
3. **`backend/kerstin/exam.py`** (new):
   - `load_presets(dir)` with validation: kinds, seconds > 0, pool sizes; raise a clear `ValueError`.
   - `ExamPlan` (dataclass: preset, parts with resolved cards) and `make_plan(preset_key, pools, seed)`, which uses `random.Random(seed)` with no repeats inside one exam.
   - `MODERATION_PREFIX` and `is_moderation(msg) -> bool`.
4. **Prompts** (`prompts.py`): `PromptStore.exam_system_prompt(plan) -> str` = persona with the scenario line replaced by a fixed exam description, plus `exam.md` filled with the cards. Exam mode ignores focus (T024).
5. **Session** (`session.py`). Refactor without changing normal-mode behaviour; all existing tests stay green:
   - Split `_turn` into the input part (gates → STT → filters → echo) and `_respond(turn_id, max_tokens=None)`, which is today's producer/consumer + metrics.
   - `async def _kerstin_says(marker: str, max_tokens: int | None = None)`:
     - turn id + 1;
     - append the marker (as a moderation user message) to history;
     - thermal check: if hot, send `thermal` with the turn and return;
     - call `_respond`.
   - `llm.stream_chat(messages, max_tokens=None)` gets an override. Use 450 tokens for `kerstin_talk`; everything else uses the default.
   - **Exam state:** `self.exam: ExamPlan | None`, `self.part_index`.
     - `start()` in exam mode sends `session` with `"exam": {"preset","title","note","parts":[{"kind","title","seconds"}]}`;
     - then `_speak_fixed` a short greeting from `exam.json` (e.g. „Hallo, ich bin Kerstin. Ich mache die Prüfung heute mit dir – viel Erfolg uns beiden!“);
     - then enters part 0, sending `{"type":"exam_part","index","kind","title","seconds","ui_text","card"}`, where `card` is the learner's card or `null`. For `kerstin_talk`, send Kerstin's card **title only**.
   - **`async def exam_next()`:**
     - `interrupt()` any running turn;
     - run the current part's finish action (`learner_talk`, first `exam_next` → follow-up question via `_kerstin_says`, and the part stays open for one answer);
     - otherwise advance: run the next part's enter action (`kerstin_talk` → talk; `dialog` → opening line; `prep` → nothing);
     - after the last part, send `{"type":"exam_part","kind":"done"}`. The client then sends the normal `end`.
   - **Collect mode:** while in `learner_talk` before its follow-up, `_turn` sends `transcript` and then `{"type":"collected","turn"}` instead of calling the LLM.
   - **History trimming:** `_messages()` keeps the latest moderation marker even when `history_max_turns` would trim it away.
   - **Feedback/hints/mistakes:**
     - `format_feedback_transcript` renders moderation markers as `--- <marker text without prefix> ---` lines, never as „Lernende Person“;
     - the feedback's „no learner lines“ check ignores markers;
     - the hint context ignores markers.
   - Log part changes at INFO (`exam part 2 dialog`), with no text.
6. **Protocol** (`main.py`, `docs/PROTOCOL.md`):
   - `start` gains `exam?: "<preset key>"` and `exam_seed?: int` (eval and tests only). An unknown preset → `error`.
   - New client message `{"type":"exam_next"}`; it's ignored outside exam mode, with an `error`.
   - New server messages: `exam_part`, `collected`.
7. **Eval: `scripts/exam_eval.py`** (new) + `make exam-eval` (`EXAM_ARGS`).
   - Runs both presets through a real `Session` with a text STT fake (same approach as `persona_eval.py`, including its working −6 dBFS buffer) and scripted learner lines per part: a 4-utterance talk, an answer, 2 questions to Kerstin, and 4 discussion/planning turns.
   - `--seed`, `--model`, `cool_down()` before every LLM call.
   - **Automatic checks:**
     - **0 LLM calls** during collect;
     - the follow-up is one question (ends with „?“, ≤ 2 sentences);
     - the Kerstin talk word count is within ±35 % of `talk_words`, with no bullets or markdown;
     - the dialog replies pass `check_reply` (incl. `meta_talk`);
     - no reply contains `[Moderation` or „Moderation“;
     - the discussion opener contains a position marker (ich finde / meiner Meinung nach / ich bin der Meinung / ich glaube);
     - the planning opener contains a proposal (wir könnten / lass uns / wie wäre es / ich schlage vor).
   - Print a summary per preset, plus **every Kerstin reply grouped by part**, for lead grading. Also report the Kerstin talk TTS/first-audio time.
8. **Tests:**
   - `backend/tests/test_exam.py` (new):
     - the real `exam.json` validates;
     - a broken preset → `ValueError`;
     - `make_plan` is deterministic per seed, with no repeated cards;
     - `is_moderation`;
     - pool minimum sizes.
   - `backend/tests/test_session.py`, with fake STT/LLM:
     - a full telc-style run (each part's enter/finish actions, the message sequence, part indices, `done`);
     - collect mode makes no LLM call and history grows;
     - the follow-up question happens exactly once;
     - `kerstin_talk` uses `max_tokens=450`;
     - markers are kept on trimming;
     - the feedback transcript renders markers as headings and has no extra „Lernende Person“ lines;
     - a thermal-hot `_kerstin_says` → `thermal`;
     - `exam_next` outside exam mode → error;
     - **normal mode is unchanged** (existing tests).
   - `backend/tests/test_prompts.py`: the exam system prompt contains all cards, no `{…}` placeholders are left, and it's identical between the warm-up and the turns.

## Files allowed to change
- `backend/prompts/exam.json` (new), `backend/prompts/exam.md` (new), `backend/kerstin/exam.py` (new)
- `backend/kerstin/prompts.py`, `backend/kerstin/session.py`, `backend/kerstin/llm.py` (`stream_chat` max_tokens override only), `backend/kerstin/main.py` (start args, `exam_next`)
- `backend/tests/test_exam.py` (new), `backend/tests/test_session.py`, `backend/tests/test_prompts.py`, `backend/tests/test_llm.py`
- `scripts/exam_eval.py` (new), `Makefile` (`exam-eval` only)
- `docs/PROTOCOL.md`
- this task file (Worker report only)

## Out of scope
- **UI** (T026): until then, exam mode is reachable only via WS/eval.
- Scoring (T025).
- Changing `persona.md` or `feedback.md`.
- Focus in exam mode.
- Server-enforced timers: the server sends `seconds` and the client (T026) does the countdown.
- Recording or storing anything new.

## Acceptance criteria
- [ ] `make test` (Python + JS) and `make lint` pass; the tests listed above exist; normal-mode tests are unchanged and green
- [ ] `make exam-eval` on `gemma4:26b` for both presets: the summary and all Kerstin replies by part are pasted. Automatic checks: 0 LLM calls in collect, 0 moderation leaks, 0 corrections, talk length within range. If one fails, say so; don't tune the checks.
- [ ] `exam.json` pools have the minimum sizes; the lead grades every card and every Kerstin reply (German, naturalness, task fit)
- [ ] Kerstin's talk: time to first audio reported (the early-clause TTS should keep it like a normal turn)
- [ ] `git diff main --stat` shows only allowed files

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
