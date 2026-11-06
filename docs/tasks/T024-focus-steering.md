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
- **Changed files:**
- **How tested:**
- **Measurements (if any):**
- **Deviations from spec / extra files touched:**
- **New dependencies (+license):**
- **Open questions:**

## Review (Claude Code fills this in)
- **Verdict:**
- **Notes:**
