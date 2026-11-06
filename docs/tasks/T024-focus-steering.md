# T024 — Focus steering from the mistake log

**Branch:** `task/T024-focus-steering` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
If the learner opts in, Kerstin uses the mistake log (T020) to create **natural chances to practise** the learner's top 1–2 weak categories:
- for *Verbposition*, she asks *warum*-questions, so the answer needs *weil … Verb*;
- for *Perfekt mit sein*, she asks about the weekend or trips.

She stays a peer. She **never corrects, never names the focus, and never talks about grammar or practising** (persona contract, D002).

## Context
- `MistakeLog.summary(days)` → `{"sessions", "categories":[{"key","label","count"}]}` (T020). Only categories are stored (D020).
- `PromptStore.system_prompt(scenario_key)` is used twice in `Session`: in the warm-up on `start` (T005, which caches the prompt prefix) and in `_messages()` for every turn. **Both must use the identical string**, or the prefix cache is wasted.
- `scripts/persona_eval.py` runs 5 scenarios × 6 scripted learner lines through a real `Session` (text only) and applies `reply_checks.check_reply` (length, corrections, English, markdown). `--persona` selects a candidate persona file.
- Latency: the focus adds about 2 lines to the system prompt. It's cached by the warm-up, so the expected cost is ≈0 ms. Measure it once.

## Spec
1. **`backend/prompts/focus.json`** (new, German). For each category, `{"instruction": str, "cues": [regex, …]}`:
   - `instruction` is **one** sentence telling Kerstin how to create opportunities, e.g.
     - `verbposition`: „Stelle ab und zu Warum-Fragen oder frage nach Meinungen, sodass die Person natürlich mit ‚weil‘, ‚dass‘ oder ‚obwohl‘ antworten kann.“
     - `perfekt_hilfsverb`: „Frage gelegentlich nach Erlebnissen, Ausflügen und Wegen in der Vergangenheit (z. B. wohin jemand gefahren oder gegangen ist).“
     - `praeposition`: „Frage gelegentlich nach Vorfreude, Ärger, Interessen oder Plänen (worauf, worüber, wofür).“
     - `kasus`: „Frage gelegentlich, mit wem, bei wem oder für wen die Person etwas macht.“
     - `adjektivendung`: „Bitte die Person ab und zu, Dinge, Orte oder Menschen genauer zu beschreiben.“
     - `genus`: „Frage gelegentlich nach konkreten Dingen und Gegenständen aus dem Alltag.“
   - `wortwahl` and `sonstiges` get **no** entry; they're never a focus.
   - `cues` are lower-case regexes used **only by the eval**, to estimate whether a reply invites the structure. For example: verbposition `\bwarum\b`, `\bwieso\b`, `\bweshalb\b`, `meinst du`, `findest du`, `glaubst du`; perfekt_hilfsverb `\bgestern\b`, `wochenende`, `\bletzte[nrs]?\b`, `\bwarst du\b`, `\bbist du\b.*\b(ge\w+en)\b`.
2. **Focus selection**, a pure function in `backend/kerstin/mistakes.py`: `pick_focus(summary: dict, available: set[str], max_n: int = 2, min_count: int = 2) -> list[str]`. It takes the top categories by count that have an instruction and count ≥ `min_count`, in summary order (ties broken by key).
3. **Prompt:** `PromptStore.system_prompt(scenario_key, focus: list[str] | None = None)` and `PromptStore.focus_instructions() -> dict[str, dict]` (`focus.json`).
   - With focus: append a fixed German block after the persona:
     ```
     ## Gesprächsimpulse (geheim)
     - <instruction 1>
     - <instruction 2>
     Erwähne diese Impulse nie. Sprich nie über Grammatik, Fehler oder Üben und korrigiere nicht. Bleib natürlich; höchstens jede zweite Antwort folgt einem Impuls.
     ```
   - With no focus, the output is byte-identical to today's (test it).
4. **Session:**
   - `Session.focus: list[str] = []`. In `start()`, compute the system prompt **once** (`self._system`), and use it in the warm-up and in `_messages()`.
   - The `session` message gains `"focus": [labels]`, an empty list when off.
5. **Start/protocol** (`main.py`, `docs/PROTOCOL.md`):
   - `start` gains an optional `use_focus: bool`, parsed strictly with `is True`.
   - If it's true and `deps.mistakes` exists: `summary(days=30)` → `pick_focus` → `Session(focus=…)`.
   - Errors → empty focus, logged as a WARNING with the type only.
   - Log `focus=<keys>` at INFO; keys aren't learner text.
6. **UI** (`index.html`, `app.js`, `style.css`), in the "Deine Schwerpunkte" box:
   - a checkbox `#useFocus` "Im Gespräch gezielt üben", default **off**, remembered in `localStorage` (try/catch);
   - `start` sends `use_focus`;
   - on `session` with a non-empty `focus`, show „Heute im Fokus: Verbposition, Kasus“ (`textContent`); hide it otherwise.
7. **Meta-talk check:** `reply_checks.has_meta_talk(text) -> bool` matches (case-insensitive, word boundaries): `fokus`, `schwerpunkt`, `grammatik`, `fehler`, `üben`, `übung`, `korrigier\w*`, `impuls\w*`, `verbposition`, `nebensatz`. It's part of `check_reply`, reported as `meta_talk`, and doesn't change any existing check.
8. **Eval** (`scripts/persona_eval.py`):
   - `--focus key[,key]` passes the focus into the session's system prompt.
   - Per run, report the existing summary plus `meta_talk` count and **invite rate**: the share of replies matching any cue of the focused categories. Also report the invite rate for the same cues **without** focus, as the baseline.
   - **Runs**, all with the same seed and `cool_down()` before every call:
     - (a) no focus;
     - (b) `--focus verbposition`;
     - (c) `--focus perfekt_hilfsverb,praeposition`.

     That's 3 × 30 replies.
   - Paste the summary tables, plus **all 30 replies of (b)** and the first 10 of (c), for lead grading (German correctness, naturalness, no meta talk). Also measure `llm_first_token_ms` p50 with and without focus (warm).
9. **Tests:**
   - `test_mistakes.py`: `pick_focus` handles order, `min_count`, the `available` filter, `max_n`, ties, an empty summary, and that `sonstiges`/`wortwahl` are never picked.
   - `test_prompts.py`: no focus → byte-identical; with focus → the block contains exactly the given instructions in order; an unknown key → `ValueError`.
   - `test_session.py`: a focus session's warm-up messages and turn messages use **the same** system string (assert equality); the `session` message carries labels; no focus → `focus: []`.
   - `test_reply_checks.py`: meta words are detected; normal sentences with "üblich" or "Fehlalarm"-like words aren't (word boundaries).
   - API/start: `use_focus:"true"` (a string) → no focus; `true` with a log containing ≥ 2 counts → focus is set (fake log).

## Files allowed to change
- `backend/prompts/focus.json` (new), `backend/kerstin/prompts.py`, `backend/kerstin/mistakes.py` (`pick_focus` only), `backend/kerstin/session.py` (start/system prompt/focus), `backend/kerstin/main.py` (start wiring), `backend/kerstin/reply_checks.py` (`has_meta_talk` only)
- `backend/tests/test_mistakes.py`, `backend/tests/test_prompts.py`, `backend/tests/test_session.py`, `backend/tests/test_reply_checks.py`
- `scripts/persona_eval.py`
- `frontend/index.html`, `frontend/app.js` (focus only), `frontend/style.css` (focus line only)
- `docs/PROTOCOL.md` (`start` + `session` rows only)
- this task file (Worker report only)

This is 16 files, but each change is small and they form one feature (lead-approved). **Don't touch `persona.md`**: the focus block is appended in code.

## Out of scope
- Changing focus mid-session.
- Storing anything new.
- An LLM-chosen focus.
- Changing `persona.md`, `feedback.md` or the classifier.
- Exam mode (T021).

## Acceptance criteria
- [ ] `make test` (Python + JS) and `make lint` pass; the tests listed above exist
- [ ] No-focus prompt is byte-identical (test); the warm-up and turn system strings are identical (test)
- [ ] Eval: every `meta_talk` hit in (a)/(b)/(c) is listed with its reply. Words like „Fehler“ or „üben“ can occur naturally („Klavier üben“), so the lead judges each hit; target: 0 genuine meta talk in (b) and (c); `check_reply` issues not worse than (a) (same seed); invite rate (b) > (a) for the verbposition cues and (c) > (a) for its cues. Paste the numbers. If one isn't met, say so; don't tune the cues to pass.
- [ ] The lead grades the pasted replies: correct German, natural, no corrections
- [ ] `llm_first_token_ms` p50 with focus ≤ without + 50 ms
- [ ] `git diff main --stat` shows only allowed files

## Manual check (Sameer, after merge)
With "Fehler-Kategorien speichern" on, do two short sessions with a few *weil … Verb* mistakes. Then tick "Im Gespräch gezielt üben" and start a new session. It should show „Heute im Fokus: Verbposition“, Kerstin should ask more *warum*-type questions, and she should never mention grammar or practising.

## Worker report (Kilo Code fills this in)
- **Changed files:** `backend/prompts/focus.json` (new), `backend/kerstin/prompts.py`, `backend/kerstin/mistakes.py` (`pick_focus` only), `backend/kerstin/session.py` (start/system prompt/focus), `backend/kerstin/main.py` (start wiring), `backend/kerstin/reply_checks.py` (`has_meta_talk` only), `backend/tests/test_mistakes.py`, `backend/tests/test_prompts.py`, `backend/tests/test_session.py`, `backend/tests/test_reply_checks.py`, `scripts/persona_eval.py`, `frontend/index.html`, `frontend/app.js`, `frontend/style.css`, `docs/PROTOCOL.md` (`start`/`session` rows only), and this task file.
- **How tested:** `make test` → **206 Python + 23 Node** tests passed; `make lint` passed; `node --check frontend/app.js` passed. New tests cover `pick_focus` order/ties/min_count/available/max_n/empty and text-category exclusion; no-focus prompt byte-identity; focus block instruction order; unknown focus key; warm-up and turn using the identical system string; focus labels in `session`; strict `use_focus:"true"` rejection and fake-log focus resolution; and `has_meta_talk` word boundaries. `persona_eval.py` ran 3 × 30 replies with `gemma4:26b`, `--seed 1234`, `--pause 2`, and `cool_down()` before every warm-up/turn. The model was already loaded; the other project's model remained loaded and was not unloaded.
- **Measurements (if any):**
  - **Eval commands:** `make persona-eval EVAL_ARGS='--model gemma4:26b --seed 1234'`; `... --focus verbposition`; `... --focus perfekt_hilfsverb,praeposition`.
  - **Invite rates (same cues):**

    | run | focus | verbposition cues | perfekt+praeposition cues | warm first-token p50 |
    |---|---|---:|---:|---:|
    | (a) | none | 7/30 = 23% | 4/30 = 13% | 152 ms |
    | (b) | verbposition | 14/30 = 47% | 3/30 = 10% | 162 ms |
    | (c) | perfekt_hilfsverb,praeposition | 8/30 = 27% | 6/30 = 20% | 166 ms |

    Target met: (b) 47% > (a) 23% for verbposition; (c) 20% > (a) 13% for its cues; focus p50 is +10/+14 ms, under the +50 ms limit. Cues were not changed after seeing these results.
  - **(a) summary (no focus):**
    ```text
Summary
model: gemma4:26b
focus: none
code                 count
--------------------------
too_long                 3
no_question              0
markdown_or_emoji        0
digits                   0
english                  0
correction               0
meta_talk                3

total replies: 30
mean sentences/reply: 2.97
mean words/reply: 31.90
invite rate (focus cues): n/a (no focus)
llm_first_token_ms p50 (warm): 152
GPU: start 52 °C, end 60 °C
    ```
  - **(b) summary (`verbposition`):**
    ```text
Summary
model: gemma4:26b
focus: verbposition
code                 count
--------------------------
too_long                 3
no_question              0
markdown_or_emoji        0
digits                   0
english                  0
correction               0
meta_talk                1

total replies: 30
mean sentences/reply: 2.90
mean words/reply: 32.63
invite rate (focus cues): 14/30 = 47%
llm_first_token_ms p50 (warm): 162
GPU: start 57 °C, end 63 °C
    ```
  - **(c) summary (`perfekt_hilfsverb,praeposition`):**
    ```text
Summary
model: gemma4:26b
focus: perfekt_hilfsverb, praeposition
code                 count
--------------------------
too_long                 3
no_question              0
markdown_or_emoji        0
digits                   0
english                  0
correction               0
meta_talk                2

total replies: 30
mean sentences/reply: 3.03
mean words/reply: 33.90
invite rate (focus cues): 6/30 = 20%
llm_first_token_ms p50 (warm): 166
GPU: start 61 °C, end 62 °C
    ```
  - **`check_reply`:** `too_long=3` in all three runs; `correction=0`, `no_question=0`, `english=0`, `digits=0`, `markdown_or_emoji=0`; `meta_talk` is 3 (a), 1 (b), 2 (c). Not worse than (a).
  - **Every `meta_talk` hit (all are on `[Korrektur erlaubt]` turns; there were no non-allowed corrections):**
    - (a):
      ```text
Meta-talk hits
1. [wg_alltag] Gerne. Du hast gesagt auf der Tisch, aber es muss auf dem Tisch heißen. Der Rest war eigentlich ganz gut und ich habe alles verstanden. Möchtest du, dass ich dir in Zukunft bei jedem Fehler helfe?
2. [arbeit_kollegen] Natürlich, das mache ich gerne. Du musst sagen: Ich habe gestern mit meinem Chef über das Projekt gesprochen. Nach dem Wort mit heißt es nämlich Dativ, also meinem Chef. Hast du sonst noch Fragen zu deiner Grammatik?
3. [pruefung_planung] Natürlich, ich helfe dir gerne. In einem Nebensatz mit weil muss das Verb am Ende stehen, also: weil es persönlicher ist. Möchtest du, dass wir später noch mehr solche Sätze üben?
      ```
    - (b):
      ```text
Meta-talk hits
1. [wg_alltag] Oh, du möchtest, dass ich dich korrigiere? Das mache ich gerne, wenn du es möchtest. Du hättest sagen müssen, dass er sein Geschirr auf den Tisch gestellt hat. Findest du, dass die Korrektur hilfreich war?
      ```
    - (c):
      ```text
Meta-talk hits
1. [freies_gespraech] Gerne, ich helfe dir. Man sagt: Ich freue mich auf den Sommer. Möchtest du, dass ich dich öfter korrigiere, oder sollen wir einfach nur ganz normal plaudern?
2. [wg_alltag] Du möchtest, dass ich dich korrigiere? Okay, kein Problem. Du musst nur sagen: Er hat sein Geschirr auf den Tisch gestellt, weil Tisch maskulin ist und hier der Akkusativ genutzt wird. War das verständlich für dich?
      ```
  - **All 30 replies of (b):**
- S1-T1: Das ist ja toll, dass du dich hier schon so wohlfühlst. Ich wohne erst seit zwei Jahren hier und finde die Stadt manchmal noch ein bisschen stressig. Was gefällt dir an Berlin am besten?
- S1-T2: Das ist schade, dass der Film nicht gut war. Welchen Film habt ihr denn im Kino gesehen? Ich gehe nämlich auch sehr gerne ins Kino, wenn die Story spannend ist.
- S1-T3: Das kann ich gut verstehen, ich hatte diese Woche auch sehr viel zu tun im Büro. Hast du denn am Wochenende schon etwas Schönes geplant, um dich zu entspannen? Vielleicht kannst du ja einfach ein bisschen ausruhen.
- S1-T4: Das Wort heißt auf Deutsch Deadline oder man kann auch Abgabetermin sagen. Ich habe gerade auch ein Problem, weil ich eine wichtige Deadline für mein Projekt am Freitag habe. Hast du in deinem Job auch oft so viel Zeitdruck?
- S1-T5: Das ist ja toll, dass du dich hier schon so wohlfühlst. Ich wohne erst seit zwei Jahren hier und finde die Stadt manchmal noch ein bisschen stressig. Was gefällt dir an Berlin am besten?
- S1-T6: Ich möchte eigentlich nicht als Lehrerin auftreten, aber wenn du es unbedingt möchtest, helfe ich dir gerne. Man sagt eigentlich: Ich freue mich auf den Sommer. Hast du denn schon Pläne für den Urlaub im Sommer?
- S2-T1: Das ist eine gute Idee. Ich finde nämlich, dass die Aufgaben momentan nicht ganz gerecht verteilt sind. Wann hättest du denn Zeit, damit wir das in Ruhe besprechen können?
- S2-T2: Das ist wirklich ärgerlich, weil man dann ja gar nicht merkt, dass man überhaupt geputzt hat. Warum räumt er sein Zeug einfach nicht direkt weg? Findest du auch, dass wir feste Regeln für das Geschirr brauchen?
- S2-T3: Das verstehe ich absolut, ich habe nämlich auch keine Lust, immer die Einzige zu sein, die Ordnung hält. Wir sollten vielleicht festlegen, dass jeder sein Geschirr sofort in die Spülmaschine stellt. Was hältst du von diesem Vorschlag?
- S2-T4: Du meinst bestimmt eine Frist oder einen Termin. Wir könnten zum Beispiel eine Frist setzen, dass alles bis zum Abend weggeräumt sein muss. Findest du das eine gute Lösung?
- S2-T5: Ja, genau das habe ich auch gesagt. Wir könnten zum Beispiel festlegen, wer an welchen Tagen für den Boden oder den Müll zuständig ist. Was meinst du, welche Aufgaben sind am wichtigsten?
- S2-T6: Oh, du möchtest, dass ich dich korrigiere? Das mache ich gerne, wenn du es möchtest. Du hättest sagen müssen, dass er sein Geschirr auf den Tisch gestellt hat. Findest du, dass die Korrektur hilfreich war?
- S3-T1: Das sehe ich ganz anders, weil ich mich im Büro viel besser konzentrieren kann. Aber ich verstehe, dass man sich dann weniger flexibel fühlt. Wie findest du das, arbeitest du lieber von zu Hause aus oder im Büro?
- S3-T2: Das tut mir leid zu hören. Warum war er denn nicht zufrieden mit dem Gespräch? Gab es ein spezielles Problem bei dem Projekt?
- S3-T3: Oh nein, das klingt wirklich stressig. Musst du denn den ganzen Samstag und Sonntag arbeiten?
- S3-T4: Du meinst bestimmt die Deadline oder den Abgabetermin. Ich finde das Wort Deadline auch ganz okay, das benutzen wir hier oft im Büro. Musst du denn wirklich am Wochenende arbeiten, um die Deadline einzuhalten?
- S3-T5: Das stimmt, zwei Tage sind schon sehr wenig, wenn man vorher mehr zu Hause arbeiten konnte. Ich finde es zumindest schade, dass wir dann weniger Zeit für den privaten Kram haben. Findest du, dass wir im Büro mehr zusammenarbeiten oder ist das nur eine Entscheidung von oben?
- S3-T6: Natürlich, das mache ich gerne. Du musst sagen: Ich habe gestern mit meinem Chef über das Projekt gesprochen. Es muss Dativ sein, also meinem Chef. Möchtest du, dass ich bei anderen Sätzen auch darauf achte?
- S4-T1: Da hast du absolut recht, der öffentliche Verkehr ist momentan noch nicht gut genug. Aber glaubst du nicht, dass weniger Autos auch die Luftqualität und die Sicherheit für Fußgänger viel schneller verbessern könnten?
- S4-T2: Das ist ein interessanter Punkt, denn die großen Lieferwagen blockieren oft die Straßen. Aber meinst du nicht, dass der Lieferverkehr auch ohne Autos besser funktionieren könnte, wenn man zum Beispiel mehr Fahrradkuriere nutzen würde?
- S4-T3: Kopenhagen ist ja wirklich ein Vorbild für Radfahrer, das kenne ich auch aus ein paar Dokumentationen. Aber glaubst du, dass man dieses Modell einfach auf eine riesige Stadt wie Berlin übertragen kann?
- S4-T4: Das Wort ist die Deadline oder auch die Frist. Meinst du das im Zusammenhang mit dem Thema Verkehr oder wolltest du etwas anderes sagen?
- S4-T5: Das habe ich vorhin schon gehört, aber ich finde, dass beides gleichzeitig wichtig ist. Wenn die Bahn besser wird, haben die Leute ja auch weniger Grund, mit dem Auto zu fahren. Was findest du am öffentlichen Verkehr in Berlin am schwierigsten?
- S4-T6: Natürlich, das mache ich gerne. Nach dem Ausdruck Meiner Meinung nach muss das Verb direkt kommen, also sagst du am besten: Meiner Meinung nach sind die Autos nicht das größte Problem. Hast du dazu noch eine Frage?
- S5-T1: Das ist eine gute Idee, weil wir dort keine Miete bezahlen müssen. Aber meinst du nicht, dass der Kursraum vielleicht ein bisschen zu klein oder langweilig ist? Wir könnten doch auch in ein schönes Café in der Nähe gehen.
- S5-T2: Das stimmt, gemeinsam etwas auszusuchen macht viel mehr Spaß. Was für ein Geschenk könnten wir denn kaufen, denkst du? Vielleicht etwas, das sie als Erinnerung an unseren Kurs behalten kann?
- S5-T3: Das ist wirklich nett von dir, danke für das Angebot! Ich kann dir gerne eine Liste mit den Namen und E-Mail-Adressen schicken. Wann hättest du denn Zeit, die Einladungen fertig zu machen?
- S5-T4: Das Wort heißt Termin oder Frist. Meinst du, wir brauchen eine feste Frist für die Anmeldung zum Essen?
- S5-T5: Das stimmt, der Kursraum ist wirklich sehr preiswert. Aber was machen wir denn mit dem Essen und den Getränken, wenn wir dort feiern? Sollen wir vielleicht einfach Pizza bestellen?
- S5-T6: Natürlich, ich helfe dir gerne. Du musst nach dem Wort weil das Verb ans Ende setzen, also: ... weil es persönlicher ist. Sollen wir jetzt weiter über das Essen sprechen?
  - **First 10 replies of (c):**
- S1-T1: Das ist ja toll, dass du dich hier schon so wohlfühlst. Ich wohne erst seit zwei Jahren hier und muss mich manchmal noch an die Bürokratie gewöhnen. In welchem Stadtteil wohnst du eigentlich?
- S1-T2: Das ist schade, ich mag langweilige Filme auch nicht so gerne. Welchen Film habt ihr denn geschaut? War es ein neuer Film oder ein alter Klassiker?
- S1-T3: Das kann ich gut verstehen, ich hatte diese Woche auch sehr viel Stress im Büro. Hast du denn schon Pläne, wie du dich am Wochenende ausruhen möchtest? Möchtest du eher gemütlich zu Hause bleiben oder etwas draußen unternehmen?
- S1-T4: Das Wort heißt Deadline oder man kann auch Abgabetermin sagen. Ich habe gerade auch so einen stressigen Abgabetermin für mein Projekt. Hast du momentan auch viel Stress bei der Arbeit oder in der Uni?
- S1-T5: Das habe ich vorhin schon gehört, aber es ist wirklich schön, dass du dich hier so wohlfühlst. Ich finde Berlin auch toll, aber die Suche nach einer neuen Wohnung ist wirklich anstrengend. Hast du denn einen Lieblingsort in der Stadt, an dem du dich besonders gerne aufhältst?
- S1-T6: Gerne, ich helfe dir. Man sagt: Ich freue mich auf den Sommer. Möchtest du, dass ich dich öfter korrigiere, oder sollen wir einfach nur ganz normal plaudern?
- S2-T1: Das finde ich eine gute Idee. Momentan habe ich das Gefühl, dass ich viel öfter putze als sonst. Hast du vielleicht heute Abend Zeit, dass wir uns das gemeinsam anschauen?
- S2-T2: Das ist wirklich ärgerlich, wenn man gerade erst fertig ist. Warum räumt er sein Geschirr nicht einfach direkt in die Spülmaschine? Möchtest du heute Abend vielleicht auch mit ihm darüber sprechen?
- S2-T3: Das verstehe ich absolut, ich möchte auch nicht die Einzige sein, die sich um den Dreck kümmert. Wir müssen wirklich eine klare Regel finden, damit alle mithelfen. Wie findest du die Idee, dass wir feste Tage für den Müll und den Boden festlegen?
- S2-T4: Du meinst wahrscheinlich eine Frist oder einen Termin. Wir könnten zum Beispiel eine Frist setzen, bis wann alles sauber sein muss. Was hältst du von diesem Vorschlag?
  - **GPU:** (a) 52→60 °C; (b) 57→63 °C; (c) 61→62 °C. No 80 °C abort. `/api/ps` kept `llama3.2:1b` loaded and used `gemma4:26b`; no other project's model was unloaded. No server was started, so port 8771/8770 was untouched.
- **Deviations from spec / extra files touched:** `PCM_1S` in `persona_eval.py` changed from silent PCM to a 1 s −6 dBFS buffer because the T013 level gate otherwise drops every scripted utterance before STT (the first attempted run failed with `empty reply`). `persona_eval.py` also calls `cool_down()` before each scenario's `Session.start()` warm-up (an LLM call), and copies `focus.json` into the temporary prompt dir when `--persona` is used. The pre-existing `.gitignore` `*.prs` line remains unstaged and is not part of this task.
- **New dependencies (+license):** None.
- **Open questions:** The `meta_talk` hits in (b)/(c) are all replies to the explicit `[Korrektur erlaubt]` learner turns; the lead should judge whether any are “genuine” focus leaks. The browser manual check remains for Sameer after merge.
## Review (Claude Code fills this in)
- **Verdict:** Accepted (2026-11-06).
- **Notes:**
  - **Code:** the system prompt is built once per session and is identical for the warm-up and all turns (tested); the no-focus prompt is byte-identical; `use_focus` is strict; a lookup error → no focus. 206 Python + 23 JS tests and lint pass. First-token cost is +10/+14 ms.
  - **Lead grading of the 30 (b) and 10 (c) replies:**
    - German correct and natural; one borderline colloquial phrase in (c) S2-T1, „Zeit, dass wir uns das anschauen“;
    - **no focus leak**: all 6 `meta_talk` hits (3 of them in the no-focus run (a)) answer explicit `[Korrektur erlaubt]` requests, the same as the baseline behaviour. Kerstin's habit of offering more corrections afterwards („Möchtest du, dass ich dich öfter korrigiere?“) predates T024 and is a persona topic, not part of this task;
    - invite rate: verbposition 47 % vs 23 % (clear); perfekt+präposition 20 % vs 13 % (modest, criterion met).
  - **Good catch by Kilo:** since T013's −55 dBFS gate, `persona_eval.py` had been feeding silent PCM that the gate dropped, so the eval was silently broken. It's fixed with a −6 dBFS buffer.
