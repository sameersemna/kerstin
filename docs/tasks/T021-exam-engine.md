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

### Round 1 — exam.md wording + eval realism

- **Round 1:** Implemented `make_plan(..., cards=...)` pinning by pool name/alias and title/question/situation; the eval now pins two card sets and runs **2 presets × 2 card sets = 4 runs** with card-matched learner lines (talk, answer, 2 Kerstin questions, 4 discussion lines: 2 pro + 2 partly agreeing, 4 planning lines only in planning). `exam.md` now says du (not ihr/euch), asks for a counterpoint after agreement, and says „Punkte oder Noten“ (no „Prüfungsmarken“). The eval gained `ihr_euch` and `counterpoint` checks.
- **Verification:** `make test` → **230 Python + 23 Node** tests pass; `make lint` passes. New tests: pinning by title/question/situation, unknown pinned title → `ValueError`, and `exam.md` contains „du an“, „Gegenpunkt“, and no „Prüfungsmarken“. No other prompt changes; `persona.md`/`feedback.md` untouched.
- **4-run results:** A/telc **PASS**; A/Goethe **FAIL** (`ihr/euch` in T7 talk); B/telc **FAIL** (planning opener lacks a proposal; `no_question` T6/T8); B/Goethe **FAIL** (`no_question` T6/T8; `ihr/euch` in T7 talk). Counterpoint after learner agreement was **true in all four**; collect-mode LLM calls **0**; talk lengths **133/163/121/174**; first-audio **461/423/429/460 ms** (headless `NoTTS`, `tts_first_ms=0`); GPU **48–71 °C**; no 80 °C abort. `gemma4:26b` ran alongside `nomic-embed-text`; no other model was unloaded. No server was started. The four failures are model behaviour, not check tuning; the lead grades them.
- **Full 4-run output (summaries + every Kerstin reply by part):**
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
GPU before praesentation_diskussion_planung part 3 dialog turn 2: 59 °C
GPU before praesentation_diskussion_planung part 3 dialog turn 3: 59 °C
GPU before praesentation_diskussion_planung part 3 dialog turn 4: 59 °C
GPU before praesentation_diskussion_planung part 3 dialog next: 59 °C
GPU before praesentation_diskussion_planung part 4 dialog turn 1: 60 °C
GPU before praesentation_diskussion_planung part 4 dialog turn 2: 61 °C
GPU before praesentation_diskussion_planung part 4 dialog turn 3: 61 °C
GPU before praesentation_diskussion_planung part 4 dialog turn 4: 62 °C
GPU before praesentation_diskussion_planung part 4 dialog next: 63 °C

## Run `praesentation_diskussion_planung / A — Homeoffice / Berlin / autofrei / Abschied` — Präsentation, Diskussion und Planung
Parts: 0:prep, 1:learner_talk, 2:kerstin_talk, 3:dialog, 4:dialog
Collect-mode LLM calls: 0
Follow-up: Das klingt nach einer sehr vernünftigen Einstellung. Glaubst du, dass die Regeln für das Homeoffice in den Firmen strenger werden sollten?  [one-question=True]
Kerstin talk: 133 words (target 130, range 84–175); markdown=False
Kerstin talk timing: first_sentence_ms=461 tts_first_ms=0 first_audio_ms=461 llm_first_token_ms=168
Discussion opener: Ich finde das Thema sehr spannend. Meiner Meinung nach sind autofreie Zonen in den Innenstädten eine super Idee, um die Luft sauberer zu machen. Was denkst du darüber?  [position=True]
Counterpoint after learner agreement: True
Planning opener: Da unser Deutschkurs nächsten Monat endet, sollten wir unbedingt ein Abschiedsfest organisieren. Ich schlage vor, dass wir eine kleine Party in einem Café oder in einem Park machen. Was hältst du davon?  [proposal=True]
Dialog check_reply: 14 replies, issues=none
Moderation leaks: 0
ihr/euch hits: 0
Overall: PASS

Replies by part

[Greeting] T0: Hallo, ich bin Kerstin. Ich mache die Prüfung heute mit dir – viel Erfolg uns beiden!

[0] prep — Vorbereitung
  (no reply)

[1] learner_talk — Dein Kurzvortrag
  T5: Das klingt nach einer sehr vernünftigen Einstellung. Glaubst du, dass die Regeln für das Homeoffice in den Firmen strenger werden sollten?  [codes: -]
  T6: Das kann ich sehr gut verstehen, das kenne ich auch von mir selbst. Wie hast du das denn gelöst, damit du nach der Arbeit wirklich Feierabend machen konntest?  [codes: -]

[2] kerstin_talk — Kerstins Kurzvortrag
  T7: Ich erzähle dir jetzt etwas über meinen Weg nach Berlin. Ich komme ursprünglich aus Göteborg in Schweden und bin vor zwei Jahren hierhergezogen, weil ich als UX-Designerin in einem kleinen Start-up arbeiten wollte. Berlin bietet einfach viel mehr Möglichkeiten für meinen Beruf als meine Heimatstadt. Am Anfang war es für mich ziemlich schwer, eine Wohnung zu finden, weil der Wohnungsmarkt hier wirklich extrem schwierig ist. Auch die Bürokratie und die vielen Ämter waren am Anfang eine große Herausforderung für mich. Aber heute liebe ich Berlin, weil es hier so viele verschiedene Menschen und kulturelle Angebote gibt. Ich gehe hier sehr gerne bouldern und koche gerne mit neuen Leuten. Mein Tipp für Leute, die neu hier sind, ist, sich schnell mit anderen zu vernetzen und nicht zu viel Angst vor der Sprache zu haben.  [codes: too_long, no_question]
  T8: Es war eine Mischung aus großer Aufregung und ein bisschen Angst vor dem Unbekannten. Ich war zwar sehr motiviert wegen des Jobs, aber alles war am Anfang so neu und fremd für mich. Hattest du bei deinem Umzug oder deinem neuen Job auch so ein Gefühl?  [codes: -]
  T9: Am meisten hat mir ein kleiner Sprachkurs und der Kontakt zu anderen Expats geholfen. So konnte ich die ersten wichtigen Sätze lernen und hatte direkt ein soziales Netzwerk. Hast du beim Deutschlernen auch eine Methode gefunden, die dir besonders gut hilft?  [codes: -]

[3] dialog — Diskussion
  T10: Ich finde das Thema sehr spannend. Meiner Meinung nach sind autofreie Zonen in den Innenstädten eine super Idee, um die Luft sauberer zu machen. Was denkst du darüber?  [codes: -]
  T11: Das stimmt, weniger Lärm macht die Stadt viel angenehmer. Aber ich mache mir Sorgen um die Menschen, die in der Stadt Geschäfte haben und ihre Waren mit Lieferwagen transportieren müssen. Glaubst du, dass die Geschäfte und Anwohner durch weniger Autos zu sehr benachteiligt werden?  [codes: -]
  T12: Das ist ein sehr guter Punkt, mehr Bewegung an der frischen Luft ist gesund für alle. Man könnte die Straßen ja so umgestalten, dass sie schöner für Fußgänger werden. Denkst du, dass man die Innenstadt trotzdem gut mit öffentlichen Verkehrsmitteln erreichen kann?  [codes: -]
  T13: Genau, das ist das Hauptproblem. Vielleicht könnte man spezielle Zeiten einführen, in denen Lieferwagen noch fahren dürfen, zum Beispiel ganz früh am Morgen. Was hältst du von so einem Kompromiss?  [codes: -]
  T14: Da hast du absolut recht, das habe ich gar nicht so stark bedacht. Wir müssten sicherstellen, dass zum Beispiel Taxis oder spezielle Shuttle-Busse weiterhin in die Zone fahren dürfen. Denkst du, man könnte die Innenstadt durch mehr barrierefreie Wege für diese Menschen attraktiver machen?  [codes: -]

[4] dialog — Gemeinsam planen
  T15: Da unser Deutschkurs nächsten Monat endet, sollten wir unbedingt ein Abschiedsfest organisieren. Ich schlage vor, dass wir eine kleine Party in einem Café oder in einem Park machen. Was hältst du davon?  [codes: -]
  T16: Das ist eine wirklich gute Idee, das spart uns viel Geld. Wir könnten den Raum ja gemütlich mit ein paar Dekorationen schmücken. Was meinst du, sollen wir jeder etwas zu essen oder zu trinken mitbringen?  [codes: -]
  T17: Ein Buffet ist super, dann haben wir eine große Auswahl und es ist nicht so viel Arbeit für eine Person. Sollen wir vielleicht eine Liste machen, damit am Ende nicht fünf Leute denselben Salat mitbringen? Und hast du eine Idee, was wir als Programm machen könnten?  [codes: -]
  T18: Das Quiz klingt richtig lustig, da müssen wir uns nur ein paar gute Fragen über unsere Zeit im Kurs überlegen. Vielleicht können wir auch ein paar Fotos aus den letzten Monaten zeigen. Wer könnte sich um die Musik kümmern und die Getränke besorgen?  [codes: -]
  T19: Das mache ich sehr gerne, ich schreibe heute Abend direkt eine Nachricht in unsere Gruppe. Dann wissen alle Bescheid, was sie zum Buffet beitragen können. Sollen wir uns vielleicht nächste Woche nach dem Unterricht kurz zusammensetzen, um die Kosten für die Dekoration und die Getränke zu besprechen?  [codes: -]
GPU before exam start: 63 °C
GPU before vortrag_diskussion part 0 prep next: 63 °C
GPU before vortrag_diskussion part 1 learner_talk collect 1: 63 °C
GPU before vortrag_diskussion part 1 learner_talk collect 2: 63 °C
GPU before vortrag_diskussion part 1 learner_talk collect 3: 63 °C
GPU before vortrag_diskussion part 1 learner_talk collect 4: 63 °C
GPU before vortrag_diskussion part 1 learner_talk follow-up: 63 °C
GPU before vortrag_diskussion part 1 learner_talk answer: 63 °C
GPU before vortrag_diskussion part 1 learner_talk next: 63 °C
GPU before vortrag_diskussion part 2 kerstin_talk question 1: 64 °C
GPU before vortrag_diskussion part 2 kerstin_talk question 2: 64 °C
GPU before vortrag_diskussion part 2 kerstin_talk next: 64 °C
GPU before vortrag_diskussion part 3 dialog turn 1: 65 °C
GPU before vortrag_diskussion part 3 dialog turn 2: 65 °C
GPU before vortrag_diskussion part 3 dialog turn 3: 65 °C
GPU before vortrag_diskussion part 3 dialog turn 4: 65 °C
GPU before vortrag_diskussion part 3 dialog next: 66 °C

## Run `vortrag_diskussion / A — Homeoffice / Berlin / autofrei / Abschied` — Vortrag und Diskussion
Parts: 0:prep, 1:learner_talk, 2:kerstin_talk, 3:dialog
Collect-mode LLM calls: 0
Follow-up: Das klingt nach einer sehr vernünftigen Einstellung. Glaubst du, dass die Regeln für das Homeoffice für die Arbeitgeber oder für die Arbeitnehmer wichtiger sind?  [one-question=True]
Kerstin talk: 163 words (target 170, range 110–229); markdown=False
Kerstin talk timing: first_sentence_ms=423 tts_first_ms=0 first_audio_ms=423 llm_first_token_ms=173
Discussion opener: Ich finde das Thema sehr spannend. Meiner Meinung nach sind autofreie Zonen in der Innenstadt eine gute Idee, um die Luftqualität und die Sicherheit für Fußgänger zu verbessern. Was hältst du von der Idee?  [position=True]
Counterpoint after learner agreement: True
Planning opener: n/a
Dialog check_reply: 9 replies, issues=none
Moderation leaks: 0
ihr/euch hits: 1
  T7: Ich möchte euch jetzt von meinem Weg nach Berlin erzählen. Ich komme ursprünglich aus Göteborg in Schweden, aber ich wollte schon immer in einer größeren Stadt leben und eine neue Kultur kennenlernen. Deshalb bin ich vor zwei Jahren nach Berlin gezogen, um hier als UX-Designerin in einem Start-up zu arbeiten. Am Anfang war vieles ziemlich schwierig für mich, besonders die Wohnungssuche war extrem stressig und kompliziert. Auch die Bürokratie und die Behörden hier in Deutschland waren am Anfang sehr anstrengend, weil alles so viel Papier braucht. Aber heute gefällt mir das Leben in Berlin sehr gut, weil es hier so viele interessante Menschen und tolle Möglichkeiten zum Bouldern gibt. Ich liebe die Freiheit und die kulturelle Vielfalt in dieser Stadt. Wenn jemand neu nach Berlin kommt, habe ich einen kleinen Tipp: Sucht euch zuerst eine feste Wohnung und seid geduldig mit den Ämtern. Man braucht viel Durchhaltevermögen, aber am Ende lohnt es sich wirklich, hier zu leben. Habt ihr dazu vielleicht auch Fragen?
Overall: FAIL

Replies by part

[Greeting] T0: Hallo, ich bin Kerstin. Ich mache die Prüfung heute mit dir – viel Erfolg uns beiden!

[0] prep — Vorbereitung
  (no reply)

[1] learner_talk — Dein Kurzvortrag
  T5: Das klingt nach einer sehr vernünftigen Einstellung. Glaubst du, dass die Regeln für das Homeoffice für die Arbeitgeber oder für die Arbeitnehmer wichtiger sind?  [codes: -]
  T6: Das kann ich sehr gut verstehen, das kenne ich auch von mir selbst. Wie hast du das denn gelöst, damit du nach der Arbeit wirklich Feierabend machen konntest?  [codes: -]

[2] kerstin_talk — Kerstins Kurzvortrag
  T7: Ich möchte euch jetzt von meinem Weg nach Berlin erzählen. Ich komme ursprünglich aus Göteborg in Schweden, aber ich wollte schon immer in einer größeren Stadt leben und eine neue Kultur kennenlernen. Deshalb bin ich vor zwei Jahren nach Berlin gezogen, um hier als UX-Designerin in einem Start-up zu arbeiten. Am Anfang war vieles ziemlich schwierig für mich, besonders die Wohnungssuche war extrem stressig und kompliziert. Auch die Bürokratie und die Behörden hier in Deutschland waren am Anfang sehr anstrengend, weil alles so viel Papier braucht. Aber heute gefällt mir das Leben in Berlin sehr gut, weil es hier so viele interessante Menschen und tolle Möglichkeiten zum Bouldern gibt. Ich liebe die Freiheit und die kulturelle Vielfalt in dieser Stadt. Wenn jemand neu nach Berlin kommt, habe ich einen kleinen Tipp: Sucht euch zuerst eine feste Wohnung und seid geduldig mit den Ämtern. Man braucht viel Durchhaltevermögen, aber am Ende lohnt es sich wirklich, hier zu leben. Habt ihr dazu vielleicht auch Fragen?  [codes: too_long]
  T8: Es war eine Mischung aus großer Aufregung und auch ein bisschen Angst vor dem Unbekannten. Ich war sehr gespannt auf das neue Abenteuer, aber die neue Sprache und die fremde Umgebung haben mich am ersten Tag auch etwas nervös gemacht. Hast du auch schon einmal in einer ganz anderen Stadt oder in einem anderen Land gelebt?  [codes: -]
  T9: Am meisten hat mir ein kleiner Sprachkurs und das Kennenlernen von anderen Expats geholfen. Es war so wichtig, Leute zu treffen, die ähnliche Erfahrungen gemacht haben. Hast du beim Sprachenlernen auch schon solche Gruppen oder Kurse besucht?  [codes: -]

[3] dialog — Diskussion
  T10: Ich finde das Thema sehr spannend. Meiner Meinung nach sind autofreie Zonen in der Innenstadt eine gute Idee, um die Luftqualität und die Sicherheit für Fußgänger zu verbessern. Was hältst du von der Idee?  [codes: -]
  T11: Das stimmt, weniger Lärm und bessere Luft sind super für die Lebensqualität. Aber ich mache mir Sorgen, dass es für die Geschäfte schwierig werden könnte, wenn die Kunden nicht mehr einfach mit dem Auto zum Laden kommen können. Denkst du, dass die Menschen dann einfach mehr online bestellen werden?  [codes: -]
  T12: Das ist ein sehr guter Punkt, mehr Bewegung an der frischen Luft ist gesund. Aber meinst du nicht, dass es für die Anwohner schwierig wird, wenn sie zum Beispiel schwere Einkäufe oder Möbel nach Hause transportieren müssen?  [codes: -]
  T13: Genau, das ist ein wichtiger Punkt. Die Logistik für die Lieferanten muss natürlich trotzdem funktionieren, sonst leidet die Versorgung in der Stadt. Findest du, dass man zum Beispiel elektrische Lastenfahrräder für die Lieferungen fördern sollte?  [codes: -]
  T14: Da hast du absolut recht, das ist ein sehr wichtiger Aspekt, den man nicht vergessen darf. Wir müssten sicherstellen, dass der öffentliche Nahverkehr oder spezielle Shuttle-Dienste sehr gut ausgebaut sind, damit alle mobil bleiben. Glaubst du, dass die Stadtverwaltung genug Geld für solche Projekte hat?  [codes: -]
GPU before exam start: 66 °C
GPU before praesentation_diskussion_planung part 0 prep next: 66 °C
GPU before praesentation_diskussion_planung part 1 learner_talk collect 1: 66 °C
GPU before praesentation_diskussion_planung part 1 learner_talk collect 2: 66 °C
GPU before praesentation_diskussion_planung part 1 learner_talk collect 3: 62 °C
GPU before praesentation_diskussion_planung part 1 learner_talk collect 4: 62 °C
GPU before praesentation_diskussion_planung part 1 learner_talk follow-up: 62 °C
GPU before praesentation_diskussion_planung part 1 learner_talk answer: 66 °C
GPU before praesentation_diskussion_planung part 1 learner_talk next: 63 °C
GPU before praesentation_diskussion_planung part 2 kerstin_talk question 1: 66 °C
GPU before praesentation_diskussion_planung part 2 kerstin_talk question 2: 67 °C
GPU before praesentation_diskussion_planung part 2 kerstin_talk next: 67 °C
GPU before praesentation_diskussion_planung part 3 dialog turn 1: 67 °C
GPU before praesentation_diskussion_planung part 3 dialog turn 2: 67 °C
GPU before praesentation_diskussion_planung part 3 dialog turn 3: 67 °C
GPU before praesentation_diskussion_planung part 3 dialog turn 4: 67 °C
GPU before praesentation_diskussion_planung part 3 dialog next: 68 °C
GPU before praesentation_diskussion_planung part 4 dialog turn 1: 68 °C
GPU before praesentation_diskussion_planung part 4 dialog turn 2: 68 °C
GPU before praesentation_diskussion_planung part 4 dialog turn 3: 68 °C
GPU before praesentation_diskussion_planung part 4 dialog turn 4: 69 °C
GPU before praesentation_diskussion_planung part 4 dialog next: 69 °C

## Run `praesentation_diskussion_planung / B — Reisen / Bouldern / Homeoffice / Wochenende` — Präsentation, Diskussion und Planung
Parts: 0:prep, 1:learner_talk, 2:kerstin_talk, 3:dialog, 4:dialog
Collect-mode LLM calls: 0
Follow-up: Das klingt wirklich sehr interessant. Warst du in den Bergen eher in einem Hotel oder hast du dort gewandert?  [one-question=True]
Kerstin talk: 121 words (target 130, range 84–175); markdown=False
Kerstin talk timing: first_sentence_ms=429 tts_first_ms=0 first_audio_ms=429 llm_first_token_ms=170
Discussion opener: Ich finde das Thema Homeoffice sehr spannend. Meiner Meinung nach ist Homeoffice eine tolle Sache, weil man so viel Zeit und Stress beim Pendeln spart. Was denkst du darüber?  [position=True]
Counterpoint after learner agreement: True
Planning opener: Hey, wir wollten doch am nächsten Wochenende etwas mit unseren Freunden unternehmen. Hast du schon eine Idee, wohin wir reisen könnten?  [proposal=False]
Dialog check_reply: 14 replies, issues={6: ['no_question'], 8: ['no_question']}
Moderation leaks: 0
ihr/euch hits: 0
Overall: FAIL

Replies by part

[Greeting] T0: Hallo, ich bin Kerstin. Ich mache die Prüfung heute mit dir – viel Erfolg uns beiden!

[0] prep — Vorbereitung
  (no reply)

[1] learner_talk — Dein Kurzvortrag
  T5: Das klingt wirklich sehr interessant. Warst du in den Bergen eher in einem Hotel oder hast du dort gewandert?  [codes: -]
  T6: Das klingt sehr friedlich. Ich mag die Ruhe am Morgen auch sehr gerne.  [codes: no_question]

[2] kerstin_talk — Kerstins Kurzvortrag
  T7: Ich möchte heute über mein Hobby Bouldern sprechen. Ich bin vor etwa einem Jahr zum Bouldern gekommen, weil eine Kollegin in meinem Start-up mich mitgenommen hat. Am Anfang war ich sehr unsicher, aber jetzt macht es mir riesigen Spaß. Was mir besonders gefällt, ist, dass man wie bei einem Rätsel über die Wand nachdenkt und nur die Kraft und die richtige Technik braucht. Ich gehe meistens zweimal pro Woche nach der Arbeit in eine Halle hier in Berlin. Das hilft mir, nach dem stressigen Büroalltag richtig abzuschalten. Durch das Bouldern habe ich auch gelernt, dass man nicht sofort ans Ziel kommt, sondern dass man geduldig sein muss und immer wieder probieren muss. Es ist ein toller Ausgleich zum Sitzen im Büro.  [codes: too_long, no_question]
  T8: Wie ich schon kurz gesagt habe, hat mich eine Kollegin aus meiner Arbeit dazu motiviert. Sie ist schon lange dabei und wollte mir die Halle zeigen.  [codes: no_question]
  T9: Ich mag besonders das Gefühl, wenn man eine schwierige Route endlich geschafft hat. Das ist wie ein kleiner Erfolg, der einen richtig glücklich macht. Findest du Sport auch so wichtig zum Entspannen?  [codes: -]

[3] dialog — Diskussion
  T10: Ich finde das Thema Homeoffice sehr spannend. Meiner Meinung nach ist Homeoffice eine tolle Sache, weil man so viel Zeit und Stress beim Pendeln spart. Was denkst du darüber?  [codes: -]
  T11: Das stimmt, die Konzentration ist zu Hause oft besser. Aber ich finde auch, dass der Kontakt zu den Kollegen fehlt, wenn man sich nur noch über den Bildschirm sieht. Findest du nicht auch, dass die Teamarbeit schwieriger wird?  [codes: -]
  T12: Das ist ein sehr wichtiger Punkt, die Flexibilität hilft Familien natürlich extrem. Trotzdem glaube ich, dass die Trennung von Arbeit und Privatleben zu Hause schwieriger wird, wenn man keinen festen Büroalltag hat. Hast du selbst schon Erfahrungen mit Homeoffice gemacht?  [codes: -]
  T13: Genau das ist mein größtes Problem dabei. Man fühlt sich manchmal ein bisschen isoliert, wenn man den ganzen Tag alleine in der Wohnung sitzt. Was meinst du, könnte man das Problem lösen, indem man öfter gemeinsame Tage im Büro plant?  [codes: -]
  T14: Da hast du absolut recht, für Leute in der Produktion oder im Service geht das natürlich gar nicht. Es ist sehr abhängig von der Art der Arbeit. Findest du, dass man für diese Berufe spezielle Lösungen braucht?  [codes: -]

[4] dialog — Gemeinsam planen
  T15: Hey, wir wollten doch am nächsten Wochenende etwas mit unseren Freunden unternehmen. Hast du schon eine Idee, wohin wir reisen könnten?  [codes: -]
  T16: Das ist eine super Idee, ich liebe den See! Sollen wir vielleicht in einer kleinen Pension oder in einer Jugendherrenunterkunft übernachten?  [codes: -]
  T17: Das ist ein sehr guter Vorschlag, gemeinsames Kochen macht viel mehr Spaß als im Restaurant. Dann können wir auch gemütlich zusammen sitzen. Wie sollen wir eigentlich dorthin kommen, fahren wir mit dem Zug oder nehmen wir das Auto?  [codes: -]
  T18: Das stimmt, im Zug können wir uns entspannen und vielleicht sogar zusammen einen Podcast hören. Dann müssen sich auch nicht alle um die Fahrt kümmern. Was könnten wir denn an dem Wochenende dort alles machen, außer wandern und schwimmen?  [codes: -]
  T19: Das klingt nach einem perfekten Plan für ein entspanntes Wochenende. Ein Picknick am See ist im Sommer immer so schön. Sollen wir uns vielleicht gemeinsam darum kümmern, dass jeder etwas zum Picknick mitbringt?  [codes: -]
GPU before exam start: 69 °C
GPU before vortrag_diskussion part 0 prep next: 69 °C
GPU before vortrag_diskussion part 1 learner_talk collect 1: 69 °C
GPU before vortrag_diskussion part 1 learner_talk collect 2: 69 °C
GPU before vortrag_diskussion part 1 learner_talk collect 3: 69 °C
GPU before vortrag_diskussion part 1 learner_talk collect 4: 69 °C
GPU before vortrag_diskussion part 1 learner_talk follow-up: 65 °C
GPU before vortrag_diskussion part 1 learner_talk answer: 69 °C
GPU before vortrag_diskussion part 1 learner_talk next: 69 °C
GPU before vortrag_diskussion part 2 kerstin_talk question 1: 70 °C
GPU before vortrag_diskussion part 2 kerstin_talk question 2: 70 °C
GPU before vortrag_diskussion part 2 kerstin_talk next: 70 °C
GPU before vortrag_diskussion part 3 dialog turn 1: 70 °C
GPU before vortrag_diskussion part 3 dialog turn 2: 70 °C
GPU before vortrag_diskussion part 3 dialog turn 3: 70 °C
GPU before vortrag_diskussion part 3 dialog turn 4: 71 °C
GPU before vortrag_diskussion part 3 dialog next: 71 °C

## Run `vortrag_diskussion / B — Reisen / Bouldern / Homeoffice / Wochenende` — Vortrag und Diskussion
Parts: 0:prep, 1:learner_talk, 2:kerstin_talk, 3:dialog
Collect-mode LLM calls: 0
Follow-up: Das klingt wirklich toll, dass du so gerne in den Bergen wanderst. Warst du dort in einem bestimmten Land oder eher in deiner Nähe?  [one-question=True]
Kerstin talk: 174 words (target 170, range 110–229); markdown=False
Kerstin talk timing: first_sentence_ms=460 tts_first_ms=0 first_audio_ms=460 llm_first_token_ms=167
Discussion opener: Ich finde, dass Homeoffice eine tolle Möglichkeit ist, flexibler zu arbeiten und Zeit zu sparen. Aber meinst du nicht auch, dass der Kontakt zum Team manchmal verloren geht, wenn man sich nicht mehr im Büro trifft?  [position=True]
Counterpoint after learner agreement: True
Planning opener: n/a
Dialog check_reply: 9 replies, issues={6: ['no_question'], 8: ['no_question']}
Moderation leaks: 0
ihr/euch hits: 1
  T7: Ich möchte euch heute etwas über mein Hobby Bouldern erzählen. Ich bin vor etwa zwei Jahren zum Bouldern gekommen, als ich nach Berlin gezogen bin. Ich wollte unbedingt neue Leute kennenlernen und eine Sportart finden, die nicht so langweilig ist. Am Anfang war es ziemlich schwer und ich hatte ein bisschen Angst vor der Höhe, aber jetzt macht es richtig Spaß. Was mir am Bouldern besonders gefällt, ist, dass man wie bei einem Rätsel denken muss. Man muss einen Weg finden, um oben an die Wand zu kommen, und das ist sehr motivierend. Ich gehe meistens zwei Mal pro Woche in eine Halle in der Nähe meiner Wohnung, am liebsten nach der Arbeit. Durch das Bouldern habe ich gelernt, dass man geduldig sein muss und nicht sofort aufgeben darf, wenn eine Route schwierig ist. Es hilft mir auch, nach einem stressigen Tag im Büro den Kopf frei zu bekommen. Man konzentriert sich nur auf die Bewegung und vergisst den Rest der Welt. Habt ihr auch ein Hobby, bei dem ihr so richtig abschalten könnt?
Overall: FAIL

Replies by part

[Greeting] T0: Hallo, ich bin Kerstin. Ich mache die Prüfung heute mit dir – viel Erfolg uns beiden!

[0] prep — Vorbereitung
  (no reply)

[1] learner_talk — Dein Kurzvortrag
  T5: Das klingt wirklich toll, dass du so gerne in den Bergen wanderst. Warst du dort in einem bestimmten Land oder eher in deiner Nähe?  [codes: -]
  T6: Das klingt sehr entspannt, ich liebe die Ruhe am Morgen auch. Ich finde es auch wichtig, dass man sich Zeit für die Natur nimmt.  [codes: no_question]

[2] kerstin_talk — Kerstins Kurzvortrag
  T7: Ich möchte euch heute etwas über mein Hobby Bouldern erzählen. Ich bin vor etwa zwei Jahren zum Bouldern gekommen, als ich nach Berlin gezogen bin. Ich wollte unbedingt neue Leute kennenlernen und eine Sportart finden, die nicht so langweilig ist. Am Anfang war es ziemlich schwer und ich hatte ein bisschen Angst vor der Höhe, aber jetzt macht es richtig Spaß. Was mir am Bouldern besonders gefällt, ist, dass man wie bei einem Rätsel denken muss. Man muss einen Weg finden, um oben an die Wand zu kommen, und das ist sehr motivierend. Ich gehe meistens zwei Mal pro Woche in eine Halle in der Nähe meiner Wohnung, am liebsten nach der Arbeit. Durch das Bouldern habe ich gelernt, dass man geduldig sein muss und nicht sofort aufgeben darf, wenn eine Route schwierig ist. Es hilft mir auch, nach einem stressigen Tag im Büro den Kopf frei zu bekommen. Man konzentriert sich nur auf die Bewegung und vergisst den Rest der Welt. Habt ihr auch ein Hobby, bei dem ihr so richtig abschalten könnt?  [codes: too_long]
  T8: Ich habe das beim Umzug nach Berlin entdeckt. Ich wollte einfach einen Sport finden, der mir hilft, den Alltag zu vergessen und neue Kontakte zu knüpfen.  [codes: no_question]
  T9: Am meisten gefällt mir das Gefühl, ein schwieriges Problem gelöst zu haben, wenn man endlich oben ist. Es ist wie ein kleines Rätsel, das man mit dem ganzen Körper lösen muss. Findest du auch, dass Sport gut gegen Stress hilft?  [codes: -]

[3] dialog — Diskussion
  T10: Ich finde, dass Homeoffice eine tolle Möglichkeit ist, flexibler zu arbeiten und Zeit zu sparen. Aber meinst du nicht auch, dass der Kontakt zum Team manchmal verloren geht, wenn man sich nicht mehr im Büro trifft?  [codes: -]
  T11: Das stimmt, die Zeitersparnis ist ein riesiger Vorteil. Trotzdem finde ich, dass die Kommunikation über Videoanrufe nie so persönlich ist wie ein kurzes Gespräch an der Kaffeemaschine. Glaubst du, dass man im Homeoffice trotzdem noch ein echtes Teamgefühl entwickeln kann?  [codes: -]
  T12: Das ist ein sehr wichtiger Punkt, die Flexibilität hilft Eltern natürlich extrem. Ich glaube aber, dass das für Kinder auch eine Herausforderung sein kann, wenn die Eltern ständig am Laptop sitzen und nicht richtig ansprechbar sind. Findest du, dass die Trennung zwischen Arbeit und Privatleben zu Hause dadurch nicht zu schwierig wird?  [codes: -]
  T13: Genau das habe ich auch befürchtet. Es ist schwierig, die spontanen Gespräche zu ersetzen, die man im Büro einfach so hat. Findest du, dass Firmen deshalb öfter Präsenztage einführen sollten?  [codes: -]
  T14: Da hast du absolut recht, für Leute in der Produktion oder im Service ist Homeoffice ja gar keine Option. Jeder Mensch braucht auch eine andere Umgebung, um wirklich produktiv zu sein. Meinst du, dass ein Modell mit zwei oder drei festen Tagen im Büro die beste Lösung für die meisten wäre?  [codes: -]

FAILURES: ['ihr/euch address', 'planning opener lacks proposal', 'dialog replies fail check_reply', 'dialog replies fail check_reply', 'ihr/euch address']
  ```

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

### Review — round 1
- **Verdict:** Changes requested (round 2). Pinning, card-matched scripts and the new checks are good. 230 Python + 23 Node tests pass, and lint passes.
- **Lead grading of all 4 runs:**
  1. **Counterpoint works.** Every discussion pushes back after agreement (delivery vans, local shops, team contact, children at home), stays friendly and offers compromises (delivery hours, cargo bikes, office days). Task fit is good in all parts.
  2. **„ihr/euch“ is still there in 2 of 4 talks** („Ich möchte euch … erzählen“, „Sucht euch …“, „Habt ihr …?“). The system-prompt rule is too far from the generation point. The talk marker „Halte jetzt deinen Vortrag.“ evokes an audience.
  3. **Planning opener B has no proposal** („Hast du schon eine Idee, wohin wir reisen könnten?“). The generic marker „Eröffne den Teil.“ doesn't carry the part's opening rule.
  4. **The `no_question` failures (T6/T8 in run B) are a check error, not a model error.** In an exam, a reaction to the partner's answer, or an answer to a question about her own talk, needs no counter-question. The persona's ask-back habit doesn't apply there. The lead changes the spec: in the exam eval, `no_question` applies only to dialog parts.
  5. **German:** 1 real slip in ≈40 replies: „Jugendherrenunterkunft“ (→ Jugendherberge). Minor: „Am meisten hat mir ein kleiner Sprachkurs und der Kontakt … geholfen“ (→ haben … geholfen), „zwei Mal“ (→ zweimal). This is within the norm, and no fix is needed.
  6. Formulaic openers repeat („Da hast du absolut recht“, „Das ist ein sehr guter Punkt“). This is noted for T025/T026 and isn't blocking.

### Follow-up (round 2) — required changes
1. **Part-specific moderation markers** (`session.py`, the marker strings only):
   - kerstin_talk: „Teil N – {title}: Halte jetzt deinen Vortrag. Du sprichst zu einer einzigen Person, deiner Gesprächspartnerin – sag ‚du‘, nie ‚ihr/euch‘.“
   - dialog whose title contains „plan“: „Teil N – {title}: Eröffne den Teil mit einem ersten konkreten Vorschlag (z. B. ‚Ich schlage vor, …‘).“
   - other dialog: „Teil N – {title}: Eröffne den Teil mit einer klaren eigenen Position.“
   Don't change `exam.md`, `persona.md` or anything else in the prompts.
2. **Eval:** apply `no_question` only to replies in `dialog` parts. Leave the learner_talk reaction and the kerstin_talk answers out of that code (they are still checked for the other codes). Don't change any other check.
3. **Tests:** marker texts per part kind (talk marker contains „du“ and „nie ‚ihr/euch‘“; planning marker contains „Vorschlag“).
4. Rerun the same 4 runs (same seed, same pinned sets). Paste summaries + every reply by part.

Allowed files (round 2): `backend/kerstin/session.py` (marker strings and a small helper only), `scripts/exam_eval.py`, `backend/tests/test_exam.py`, this task file.
