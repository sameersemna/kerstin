# T017 — Feedback explanation language: English / German setting + UI

**Branch:** `task/T017-feedback-language` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
The learner chooses whether the 💡 explanations in the end-of-session feedback are in **English** or **German**, using a selector in the UI. The choice is remembered in the browser, and there's a server default for clients that don't send one (D008, resolved: configurable).

## Context
- `backend/prompts/feedback.md` hard-codes `💡 Kurze Erklärung auf Englisch (ein Satz)`. Headings and the "Tipp" are German anyway, and stay German.
- `PromptStore.feedback_prompt(transcript)` does `tpl.replace("{transcript}", transcript)`.
- `Session.feedback()` (thermal check, then LLM) is called from `main.py` on `{"type":"end"}`.
- The frontend already has the same pattern for a remembered `<select>`: `#micMode` + `localStorage` in try/catch (T014).

## Spec
1. **Config:** `feedback_lang: Literal["en", "de"] = "en"` (`KERSTIN_FEEDBACK_LANG`); add it to `.env.example`.
2. **Prompt** (`backend/prompts/feedback.md`):
   - Replace the 💡 line with `💡 Kurze Erklärung auf {explanation_language} (ein Satz)`.
   - Add one line under the structure: `Schreibe alle 💡-Erklärungen auf {explanation_language}; alles andere auf Deutsch.`

   No other prompt change (T016 does quality).
3. **`PromptStore.feedback_prompt(transcript: str, lang: str = "en") -> str`:**
   - `en` → `Englisch`.
   - `de` → `Deutsch (einfache Sprache, mit Fachbegriffen wie Akkusativ, Dativ, Perfekt)`.
   - Unknown → `ValueError`.
   - Replace `{explanation_language}` **before** `{transcript}`, so learner text can never inject a placeholder.
4. **Session/protocol:**
   - `Session.feedback(lang: str | None = None)`: `None` or invalid → `deps.feedback_lang` (new `Deps` field, wired in `main.py` from settings). Log an invalid value at INFO, without the transcript.
   - `main.py` passes `data.get("feedback_lang")` from the `end` message.
   - `docs/PROTOCOL.md`: `{"type":"end","feedback_lang"?:"en"|"de"}`. Optional; invalid values fall back to the server default.
5. **UI:**
   - **`frontend/index.html`:** in `.controls`, a `<select id="feedbackLang" aria-label="Sprache der Erklärungen">` with `Erklärungen: Englisch` (`en`) and `Erklärungen: Deutsch` (`de`).
   - **`frontend/app.js`:**
     - Default `en`; restore and store it in `localStorage` key `kerstin.feedbackLang`, in try/catch (same as `micMode`).
     - `end()` sends `{"type":"end","feedback_lang": <value>}`.
     - The choice can be changed at any time; it applies when "Beenden & Feedback" is pressed.
   - **`frontend/style.css`:** nothing, or the minimum for consistent sizing with `#micMode`.
6. **Tests:**
   - `backend/tests/test_prompts.py` (new):
     - `en` → contains `Englisch` and no `{explanation_language}`;
     - `de` → contains `Deutsch (einfache Sprache`;
     - invalid → `ValueError`;
     - a transcript containing the literal `{explanation_language}` stays unchanged in the output.
   - `backend/tests/test_session.py`:
     - `feedback("de")` → the LLM prompt contains the German label;
     - `feedback()` → server default;
     - `feedback("fr")` → server default, no exception.
7. **Before/after samples** (CLAUDE.md prompt rule): with a throwaway, uncommitted snippet, generate one feedback per language for the same short invented transcript with 3 learner errors, on `gemma4:26b`. Check `nvidia-smi` first and stop at ≥ 76 °C. Paste both into the report, plus the current (English) output as "before".

## Files allowed to change
- `backend/kerstin/config.py`, `backend/kerstin/prompts.py`, `backend/kerstin/session.py` (`feedback()` + `Deps` field), `backend/kerstin/main.py` (wiring + `end` arg)
- `backend/prompts/feedback.md` (spec 2 only)
- `backend/tests/test_prompts.py` (new), `backend/tests/test_session.py`
- `frontend/index.html`, `frontend/app.js` (feedbackLang only), `frontend/style.css` (only if needed)
- `docs/PROTOCOL.md` (`end` row only), `.env.example`
- this task file (Worker report only)

## Out of scope
- More languages.
- Translating headings or UI text.
- Regenerating feedback after it was shown.
- Persona/conversation language.
- Feedback quality tuning (T016).

## Acceptance criteria
- [ ] `make test` (Python + JS) and `make lint` pass; the tests listed above exist
- [ ] The two real samples show 💡 lines in the chosen language, with everything else in German
- [ ] UI: the selector is visible next to the mic mode, its value survives a reload, and `end` carries `feedback_lang` (show the code path in the report)
- [ ] `git diff main --stat` shows only allowed files

## Manual check (Sameer, after merge)
Choose "Erklärungen: Deutsch", have a short conversation with a deliberate mistake, and press "Beenden & Feedback". The 💡 lines should be in German. Reload: the selector still says Deutsch.

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
