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
- **Changed files:** `backend/prompts/exam.json` (new), `backend/prompts/exam.md` (new), `backend/kerstin/exam.py` (new), `backend/kerstin/prompts.py`, `backend/kerstin/session.py`, `backend/kerstin/llm.py` (`stream_chat` max_tokens only), `backend/kerstin/main.py`, `backend/tests/test_exam.py` (new), `backend/tests/test_session.py`, `backend/tests/test_prompts.py`, `backend/tests/test_llm.py`, `scripts/exam_eval.py` (new), `Makefile` (`exam-eval` only), `docs/PROTOCOL.md`, and this task file.
- **How tested:** `make test` → **227 Python + 23 Node** tests passed; `make lint` passed. New tests cover real `exam.json` validation, broken kind/seconds/pool sizes, deterministic no-repeat plans, moderation detection, exam card/prompt hygiene, full telc-style enter/finish/message/part/done flow, collect mode (0 LLM calls, history grows), one follow-up, `kerstin_talk` `max_tokens=450`, marker retention on trimming, marker headings in feedback and marker-free hint context, thermal `_kerstin_says`, `exam_next` outside exam mode, and unchanged normal mode. `make exam-eval EXAM_ARGS='--model gemma4:26b --seed 1234'` ran both presets on the real Session; 20 LLM calls total.
- **Measurements (if any):**
  - Card pools: `talk_topics` 8, `kerstin_topics` 4, `discussion_questions` 8, `planning_tasks` 6; `exam.json`/`exam.md` contain no official brand names (tested). `exam.md` has no placeholders left.
  - Eval summary: both presets **Overall PASS**; **collect-mode LLM calls 0**; follow-up one question true; **0 moderation leaks**; **0 dialog `check_reply` issues** (14 and 9 replies); talk markdown false; talk word counts 128/130 (range 84–175) and 170/170 (range 110–229); discussion opener position true for both; planning proposal true for the preset that has planning (Goethe-style preset has no planning part, so n/a).
  - Kerstin talk first-audio (headless `NoTTS`, so `tts_first_ms=0`): telc-style `first_sentence_ms=447`, `first_audio_ms=447`, `llm_first_token_ms=165`; Goethe-style `first_sentence_ms=329`, `first_audio_ms=329`, `llm_first_token_ms=162`.
  - GPU during eval: 48→65 °C; no 80 °C abort. `gemma4:26b` was loaded alongside the other project's `llama3.2:1b`; neither was unloaded. No server was started (port 8771/8770 untouched).
  - Full eval output (summary + every Kerstin reply by part):
    ```text
.venv/bin/python scripts/exam_eval.py --model gemma4:26b --seed 1234
Model: gemma4:26b | seed: 1234 | cool_down: 76→70 °C
GPU before exam start: 48 °C
GPU before praesentation_diskussion_planung part 0 prep next: 48 °C
GPU before praesentation_diskussion_planung part 1 learner_talk collect 1: 48 °C
GPU before praesentation_diskussion_planung part 1 learner_talk collect 2: 48 °C
GPU before praesentation_diskussion_planung part 1 learner_talk collect 3: 48 °C
GPU before praesentation_diskussion_planung part 1 learner_talk collect 4: 48 °C
GPU before praesentation_diskussion_planung part 1 learner_talk follow-up: 48 °C
GPU before praesentation_diskussion_planung part 1 learner_talk answer: 54 °C
GPU before praesentation_diskussion_planung part 1 learner_talk next: 55 °C
GPU before praesentation_diskussion_planung part 2 kerstin_talk question 1: 57 °C
GPU before praesentation_diskussion_planung part 2 kerstin_talk question 2: 57 °C
GPU before praesentation_diskussion_planung part 2 kerstin_talk next: 58 °C
GPU before praesentation_diskussion_planung part 3 dialog turn 1: 58 °C
GPU before praesentation_diskussion_planung part 3 dialog turn 2: 58 °C
GPU before praesentation_diskussion_planung part 3 dialog turn 3: 59 °C
GPU before praesentation_diskussion_planung part 3 dialog turn 4: 59 °C
GPU before praesentation_diskussion_planung part 3 dialog next: 59 °C
GPU before praesentation_diskussion_planung part 4 dialog turn 1: 60 °C
GPU before praesentation_diskussion_planung part 4 dialog turn 2: 60 °C
GPU before praesentation_diskussion_planung part 4 dialog turn 3: 61 °C
GPU before praesentation_diskussion_planung part 4 dialog turn 4: 62 °C
GPU before praesentation_diskussion_planung part 4 dialog next: 62 °C

## Preset `praesentation_diskussion_planung` — Präsentation, Diskussion und Planung
Parts: 0:prep, 1:learner_talk, 2:kerstin_talk, 3:dialog, 4:dialog
Collect-mode LLM calls: 0
Follow-up: Das hast du sehr interessant erklärt. Warst du in letzter Zeit selbst schon in einem neuen Land oder einer anderen Stadt im Urlaub?  [one-question=True]
Kerstin talk: 128 words (target 130, range 84–175); markdown=False
Kerstin talk timing: first_sentence_ms=447 tts_first_ms=0 first_audio_ms=447 llm_first_token_ms=165
Discussion opener: Ich finde das Thema sehr aktuell. Meiner Meinung nach sind autofreie Zonen in der Innenstadt eine wirklich gute Idee für die Umwelt. Was denkst du darüber?  [position=True]
Planning opener: Ich finde die Idee toll, dass wir unser Ende des Deutschkurses gemeinsam feiern sollten. Wir könnten zum Beispiel etwas Schönes organisieren, damit wir uns alle noch einmal in Ruhe verabschieden können. Was hältst du davon, wenn wir eine kleine Party in einem Park machen?  [proposal=True]
Dialog check_reply: 14 replies, issues=none
Moderation leaks: 0
Overall: PASS

Replies by part

[Greeting] T0: Hallo, ich bin Kerstin. Ich mache die Prüfung heute mit dir – viel Erfolg uns beiden!

[0] prep — Vorbereitung
  (no reply)

[1] learner_talk — Dein Kurzvortrag
  T5: Das hast du sehr interessant erklärt. Warst du in letzter Zeit selbst schon in einem neuen Land oder einer anderen Stadt im Urlaub?  [codes: -]
  T6: Das kann ich gut verstehen, der Anfang in einem neuen Job ist immer sehr stressig. Musstest du in dieser Zeit auch viel neue Fachbegriffe auf Deutsch lernen?  [codes: -]

[2] kerstin_talk — Kerstins Kurzvortrag
  T7: Ich möchte euch jetzt etwas über meinen Weg nach Berlin erzählen. Ich komme ursprünglich aus Schweden, aus Göteborg, aber ich bin vor zwei Jahren nach Berlin gezogen, weil ich hier eine Stelle als UX-Designerin in einem kleinen Start-up gefunden habe. Am Anfang war alles ziemlich schwer für mich, besonders die Wohnungssuche in dieser Stadt war ein echter Albtraum und ich war oft frustriert wegen der Bürokratie. Aber heute gefällt mir das Leben in Berlin sehr gut, weil es so viele internationale Menschen und tolle Cafés gibt. Ich gehe hier auch gerne bouldern, um Stress abzubauen. Mein Tipp für Neuzugezogene ist, dass man nicht sofort perfekt Deutsch sprechen muss, sondern einfach Leute kennenlernen und mutig sein sollte. Habt ihr auch schon mal überlegt, in eine andere Stadt zu ziehen?  [codes: too_long]
  T8: Es war wirklich sehr stressig, weil ich mich einsam gefühlt habe und die Sprache noch nicht so gut war. Besonders die Behördengänge waren schwierig, weil alles so kompliziert klingt. Wie war das denn für dich in deinem neuen Job?  [codes: -]
  T9: Ich habe gelernt, dass man Geduld haben muss und dass es hilft, sich Hilfe zu suchen. Man darf nicht alles alleine versuchen, wenn man nicht weiterkommt. Hast du auch so etwas gelernt, als du deine Erfahrungen gemacht hast?  [codes: -]

[3] dialog — Diskussion
  T10: Ich finde das Thema sehr aktuell. Meiner Meinung nach sind autofreie Zonen in der Innenstadt eine wirklich gute Idee für die Umwelt. Was denkst du darüber?  [codes: -]
  T11: Da hast du absolut recht, die Busse und Bahnen müssen zuverlässiger werden, damit die Leute auch darauf verzichten können. Aber glaubst du nicht, dass die Geschäfte in der Stadt Probleme bekommen könnten, wenn man nicht mehr mit dem Auto direkt dorthin fahren kann?  [codes: -]
  T12: Das ist ein sehr wichtiger Punkt. Ich denke, man müsste für diese Menschen spezielle Lösungen finden, zum Beispiel Lieferdienste oder Parkplätze am Rand der Zone. Meinst du, dass die Anwohner mit der Situation zufrieden wären, wenn es weniger Verkehr gibt?  [codes: -]
  T13: Das ist ein guter erster Schritt. Vielleicht könnten wir in einem Park oder in einem Gemeinschaftsraum feiern, weil das nicht so teuer ist. Hast du schon eine Idee, wo wir feiern könnten?  [codes: -]
  T14: Das ist super, danke! Dann könnten wir zum Beispiel Saft, Wasser und vielleicht auch ein bisschen Limonade kaufen. Sollen wir uns auch um das Essen kümmern oder wäre es besser, wenn jeder einfach eine Kleinigkeit selbst mitbringt?  [codes: -]

[4] dialog — Gemeinsam planen
  T15: Ich finde die Idee toll, dass wir unser Ende des Deutschkurses gemeinsam feiern sollten. Wir könnten zum Beispiel etwas Schönes organisieren, damit wir uns alle noch einmal in Ruhe verabschieden können. Was hältst du davon, wenn wir eine kleine Party in einem Park machen?  [codes: -]
  T16: Das ist ein wichtiger Punkt für die Stadtplanung, aber für unser Abschiedsfest im Park ist das vielleicht weniger wichtig. Sollen wir uns vielleicht überlegen, was wir an Essen machen wollen? Findest du es gut, wenn wir gemeinsam Pizza bestellen?  [codes: -]
  T17: Das ist ein schwieriges Problem, aber für unser Fest im Park müssen wir uns ja nicht so viele Sorgen um die Autofahrer machen. Wir sollten uns lieber darauf konzentrieren, dass alle Gäste gut an den Ort kommen können. Was hältst du davon, wenn wir auch ein bisschen Musik oder ein kleines Programm planen, damit es nicht langweilig wird?  [codes: -]
  T18: Das stimmt, die Suche nach einem Ort ist das Wichtigste. Wir könnten ja vielleicht im Park am Gleisdreieck feiern, weil man dort sehr gut mit der U-Bahn hinkommt. Hast du eine Idee, was wir für das Programm machen könnten?  [codes: -]
  T19: Das ist wirklich sehr lieb von dir, danke! Dann können wir uns ja zusammen überlegen, wie viel Geld wir insgesamt ausgeben wollen. Meinst du, wir sollten alle Teilnehmer bitten, einen kleinen Beitrag zu zahlen?  [codes: -]
GPU before exam start: 62 °C
GPU before vortrag_diskussion part 0 prep next: 62 °C
GPU before vortrag_diskussion part 1 learner_talk collect 1: 62 °C
GPU before vortrag_diskussion part 1 learner_talk collect 2: 62 °C
GPU before vortrag_diskussion part 1 learner_talk collect 3: 58 °C
GPU before vortrag_diskussion part 1 learner_talk collect 4: 58 °C
GPU before vortrag_diskussion part 1 learner_talk follow-up: 58 °C
GPU before vortrag_diskussion part 1 learner_talk answer: 62 °C
GPU before vortrag_diskussion part 1 learner_talk next: 62 °C
GPU before vortrag_diskussion part 2 kerstin_talk question 1: 63 °C
GPU before vortrag_diskussion part 2 kerstin_talk question 2: 64 °C
GPU before vortrag_diskussion part 2 kerstin_talk next: 64 °C
GPU before vortrag_diskussion part 3 dialog turn 1: 64 °C
GPU before vortrag_diskussion part 3 dialog turn 2: 64 °C
GPU before vortrag_diskussion part 3 dialog turn 3: 64 °C
GPU before vortrag_diskussion part 3 dialog turn 4: 65 °C
GPU before vortrag_diskussion part 3 dialog next: 65 °C

## Preset `vortrag_diskussion` — Vortrag und Diskussion
Parts: 0:prep, 1:learner_talk, 2:kerstin_talk, 3:dialog
Collect-mode LLM calls: 0
Follow-up: Das klingt wirklich interessant. Welches Land hast du denn als Reiseziel am liebsten?  [one-question=True]
Kerstin talk: 170 words (target 170, range 110–229); markdown=False
Kerstin talk timing: first_sentence_ms=329 tts_first_ms=0 first_audio_ms=329 llm_first_token_ms=162
Discussion opener: Ich finde das Thema sehr spannend. Meiner Meinung nach sind autofreie Zonen eine gute Idee für die Lebensqualität in der Stadt. Was denkst du darüber?  [position=True]
Planning opener: n/a
Dialog check_reply: 9 replies, issues=none
Moderation leaks: 0
Overall: PASS

Replies by part

[Greeting] T0: Hallo, ich bin Kerstin. Ich mache die Prüfung heute mit dir – viel Erfolg uns beiden!

[0] prep — Vorbereitung
  (no reply)

[1] learner_talk — Dein Kurzvortrag
  T5: Das klingt wirklich interessant. Welches Land hast du denn als Reiseziel am liebsten?  [codes: -]
  T6: Das klingt nach einer sehr intensiven Zeit. War der Anfang in der Firma sehr stressig für dich?  [codes: -]

[2] kerstin_talk — Kerstins Kurzvortrag
  T7: Ich möchte euch heute kurz erzählen, wie ich nach Berlin gekommen bin. Ich komme ursprünglich aus Schweden, genauer gesagt aus Göteborg, und bin vor zwei Jahren hierhergezogen. Ich habe mich für Berlin entschieden, weil ich als UX-Designerin in einem Start-up arbeiten wollte und die Stadt einfach sehr dynamisch finde. Am Anfang war es aber nicht alles so einfach. Besonders das Finden einer Wohnung war sehr schwer und stressig, weil es so viele Bewerber gibt. Auch die Behörden hier in Deutschland waren für mich am Anfang ein bisschen kompliziert, weil alles so viel Papierkram bedeutet. Aber heute gefällt mir das Leben in Berlin sehr gut. Ich liebe die vielen Möglichkeiten, zum Beispiel die Kletterhallen zum Bouldern oder die vielen internationalen Cafés. Ich lerne auch gerade intensiv Deutsch an der Volkshochschule. Mein Tipp für Leute, die neu hier sind, ist, dass man mutig sein muss und schnell Kontakt zu anderen Menschen suchen sollte. Wenn man Freunde findet, fühlt man sich viel weniger einsam. Habt ihr auch Fragen zu meinem Weg nach Berlin?  [codes: too_long]
  T8: Es war wirklich sehr aufregend, aber auch ein bisschen einsam. Ich kannte ja noch niemanden hier und musste mich erst einmal an die deutsche Sprache und die Kultur gewöhnen. Hast du dich auch schon einmal in einer neuen Stadt oder einem neuen Land so gefühlt?  [codes: -]
  T9: Ich habe gelernt, dass man nicht sofort alles perfekt machen muss und dass Geduld sehr wichtig ist. Außerdem ist es wichtig, sich Hilfe zu suchen, wenn man bei den Behörden oder der Wohnungssuche nicht weiterkommt. Hast du in deiner neuen Umgebung auch schon solche wichtigen Lektionen gelernt?  [codes: -]

[3] dialog — Diskussion
  T10: Ich finde das Thema sehr spannend. Meiner Meinung nach sind autofreie Zonen eine gute Idee für die Lebensqualität in der Stadt. Was denkst du darüber?  [codes: -]
  T11: Da stimme ich dir absolut zu. Wenn die Busse und Bahnen nicht zuverlässig sind, werden die Leute die Autos nicht stehen lassen. Glaubst du, dass die Menschen in Berlin bereit wären, auf das Auto zu verzichten, wenn der öffentliche Verkehr besser wäre?  [codes: -]
  T12: Das ist ein sehr wichtiger Punkt. Besonders Leute, die außerhalb wohnen oder im Beruf zum Beispiel Handwerker sind, brauchen ein Auto. Findest du, dass man für diese Gruppen spezielle Ausnahmen oder Lösungen finden könnte?  [codes: -]
  T13: Das ist ein guter Anfang. Meinst du damit, dass wir erst einmal einen bestimmten Stadtteil suchen sollten, in dem wir das Projekt testen können?  [codes: -]
  T14: Das ist sehr lieb von dir, danke! Ich kann mich dann um die Planung der Aktivitäten und die Suche nach dem Ort kümmern. Sollen wir uns vielleicht am nächsten Wochenende treffen, um alles gemeinsam zu besprechen?  [codes: -]

All automatic checks passed.
    ```
- **Deviations from spec / extra files touched:** `exam_eval.py` uses `NoTTS` (same headless approach as `persona_eval.py`), so `tts_first_ms` is 0; `first_audio_ms` reports the first-sentence/first-audio availability. The Goethe-style preset has no planning part, so its planning-opener check prints n/a by design. Kerstin's talk is legitimately longer than normal turns and is excluded from `check_reply`; its reply is still shown with its `too_long` code. The pre-existing `.gitignore` `*.prs` line remains unstaged and is not part of this task.
- **New dependencies (+license):** None.
- **Open questions:** The T026 UI is out of scope; the browser/manual check remains for Sameer. The lead grades all cards and the pasted Kerstin replies.

## Review (Claude Code fills this in)
- **Verdict:** Changes requested (round 1): prompt wording + eval realism. The engine is accepted.
- **Notes:**
  - **Engine:** the `_turn`/`_respond` split keeps normal mode green; collect mode makes 0 LLM calls; markers are kept on trim and rendered as headings; the system prompt is fixed per session. 227 Python + 23 JS tests and lint pass. There are no brand names. The cards are correct, idiomatic and original (lead-checked all 26).
  - **Lead grading of all replies:**
    1. **The eval script misaligns learner lines.** In the telc-style discussion, turns 3–4 are planning lines (party); in the planning part, turns 1–2 are discussion lines (cars). The learner talk/answer doesn't match the drawn card either: the follow-up asks about holidays, and the answer is about a new job. Task fit can't be judged like this.
    2. **„euch/ihr“:** Kerstin's talk says „Ich möchte euch … erzählen“, „Habt ihr …?“. Her partner is one person (du).
    3. **The discussion has no friction:** after a pro opener and a pro learner, she says „Da stimme ich dir absolut zu“. An exam discussion needs counterpoints.
    4. **German slips** (3 of ≈30 replies, within gemma4's known ≈5 %): „viel neue Fachbegriffe“ (→ viele), „Am Anfang war es aber nicht alles so einfach“, „unser Ende des Deutschkurses“ (→ das Ende unseres Deutschkurses). The longer talk raises the exposure. Noted; no fix by prompt.
    5. `exam.md` says „Prüfungsmarken“, which isn't a word.

### Follow-up (round 1) — required changes
1. **Eval realism** (`exam.py`, `exam_eval.py`):
   - `make_plan(..., cards: dict[str, str] | None = None)` pins cards by title or question (eval/tests only; an unknown title → `ValueError`).
   - The eval pins one card per part and uses scripted learner lines **written for that card**:
     - talk (4 utterances) + an answer that fits a plausible follow-up;
     - 2 questions about Kerstin's pinned card;
     - 4 discussion lines **for the pinned question**: two pro, then two that partly agree, so the counterpoint behaviour shows;
     - 4 planning lines **for the pinned task** (telc-style only).
   - Run both presets with **two different pinned card sets** (4 runs).
2. **`exam.md` wording:**
   - „Sprich die Lernende immer mit du an, auch in deinem Vortrag (nicht ‚ihr/euch‘).“
   - Discussion: „Wenn die Lernende dir zustimmt, bring einen Gegenpunkt oder eine Einschränkung, damit eine echte Diskussion entsteht; bleib freundlich.“
   - Replace „Punkte, Noten oder Prüfungsmarken“ with „Punkte oder Noten“.

   No other prompt change.
3. **Eval checks:**
   - add `ihr_euch` (regex `\b(ihr|euch|euer|eure\w*)\b`, excluding „Ihr“ at the start of a sentence used as a formal possessive; simple is fine) on all replies;
   - add `counterpoint` (aber / allerdings / andererseits / trotzdem / ich bin mir nicht sicher / nicht ganz) in at least one discussion reply after the learner agrees.
4. Paste the 4 runs: summaries + every reply by part. The lead grades again.
5. Tests: the `cards` override (pinning, unknown title → `ValueError`); an `exam.md` sanity test (contains „du an“, no „Prüfungsmarken“).

Allowed files (round 1): `backend/prompts/exam.md`, `backend/kerstin/exam.py`, `scripts/exam_eval.py`, `backend/tests/test_exam.py`, `backend/tests/test_prompts.py`, this task file.
