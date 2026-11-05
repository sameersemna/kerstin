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
- **Changed files:** `backend/kerstin/config.py`, `backend/kerstin/prompts.py`, `backend/kerstin/session.py` (`feedback()` + `Deps.feedback_lang`), `backend/kerstin/main.py`, `backend/prompts/feedback.md` (two specified lines only), `backend/tests/test_prompts.py` (new), `backend/tests/test_session.py`, `frontend/index.html`, `frontend/app.js` (`feedbackLang` only), `docs/PROTOCOL.md` (`end` row only), `.env.example`, this task file.
- **How tested:** `make test` → 118 Python tests + 23 Node tests passed; `make lint` passed. `test_prompts.py` covers en/de/invalid/default and transcript placeholder injection; `test_session.py` covers requested German, server default, and invalid fallback. The before/after samples below were generated with a throwaway heredoc (no committed script) on `gemma4:26b`, using the same invented transcript with three errors (`seit zwei Jahre`; `weil es gibt`; `weil ich brauche`). `nvidia-smi --query-gpu=temperature.gpu` was checked before each run; all temperatures stayed below 76 °C.
- **Measurements (if any):** GPU temperatures: before 47→58 °C, after-en 49→60 °C, after-de 60→63 °C.
- **Deviations from spec / extra files touched:** None.
- **New dependencies (+license):** None.
- **Open questions:** None.

UI code path:
```js
function end() {
  // ...
  ws.send(JSON.stringify({ type: "end", feedback_lang: feedbackLang }));
}
$("feedbackLang").value = feedbackLang;
$("feedbackLang").onchange = (e) => {
  feedbackLang = e.target.value === "de" ? "de" : "en";
  try { localStorage.setItem(FEEDBACK_LANG_KEY, feedbackLang); } catch {}
};
```
`feedbackLang` is restored from `localStorage["kerstin.feedbackLang"]` in a try/catch at startup and defaults to `en`.

### Before (current English prompt)
```markdown
### Was gut war
*   **Kommunikative Kompetenz:** Du hast alle Fragen verstanden und konntest deine persönliche Situation (Wohnort, Beruf, Gefühle) klar und verständlich ausdrücken.
*   **Struktur:** Du hast bereits komplexere Satzstrukturen verwendet (Hauptsatz + Nebensatz mit „aber“ und „weil“), um deine Argumente zu begründen.

### Wichtigste Fehler
*   ❌ ...seit zwei Jahre...
    ✅ ...seit zwei Jahren...
    💡 The preposition "seit" always requires the dative case, and the plural dative ending is "-n".
*   ❌ ...weil es gibt viele Möglichkeiten...
    ✅ ...weil es viele Möglichkeiten gibt.
    💡 In a subordinate clause starting with "weil", the conjugated verb must move to the very end of the sentence.
*   ❌ ...weil ich brauche mehr Geld.
    ✅ ...weil ich mehr Geld brauche.
    💡 Similar to the previous error, the verb "brauche" must be placed at the end of the "weil"-clause.

### Besser ausdrücken
*   **Statt:** „Die Mieten sind zu teuer für mich.“
    **Besser (B2):** „Die Mietpreise sind für mich kaum noch bezahlbar.“ (Using more specific vocabulary like *bezahlbar* or *Mietpreise*).
*   **Statt:** „Ich bin auch gern in Berlin...“
    **Besser (B2):** „Ich fühle mich in Berlin sehr wohl...“ (Using the reflexive verb *sich wohlfühlen* sounds more natural when talking about living in a city).

### Tipp für das nächste Gespräch
Konzentriere dich auf die **Verbposition in Nebensätzen**. Übe gezielt Sätze mit „weil“, „dass“ und „obwohl“, damit das Verb am Ende steht – das ist ein entscheidender Punkt für das B2-Niveau.
```

### After: Erklärungen Englisch
```markdown
### Was gut war
* **Flüssiger Gesprächsfluss:** Du konntest direkt auf die Fragen reagieren und deine Meinung zu den Mieten und der Arbeit äußern.
* **Gute Satzverknüpfung:** Du hast bereits Konnektoren wie „aber“ und „weil“ benutzt, um komplexere Sätze zu bilden.
* **Wortschatz:** Die Verwendung von Begriffen wie „Mieten“, „Möglichkeiten“ und „arbeiten als“ war absolut passend für das Thema.

### Wichtigste Fehler
* ❌ „Ich wohne seit zwei Jahre in Berlin“
* ✅ „Ich wohne seit zwei Jahren in Berlin“
* 💡 The preposition „seit“ requires the dative case, so "Jahre" needs the "-n" ending.

* ❌ „...weil es gibt viele Möglichkeiten“
* ✅ „...weil es viele Möglichkeiten gibt“
* 💡 In a subordinate clause starting with "weil", the conjugated verb must move to the very end of the sentence.

* ❌ „...weil ich brauche mehr Geld.“
* ✅ „...weil ich mehr Geld brauche.“
* 💡 Just like the previous error, the verb "brauche" must be placed at the end of the "weil"-clause.

### Besser ausdrücken
* „Die Mieten sind zu teuer für mich.“ $\rightarrow$ „Die Mietpreise sind für mich leider kaum noch bezahlbar.“ (Klingt etwas fortgeschrittener/B2).
* „Ich suche eine neue Arbeit, weil ich mehr Geld brauche.“ $\rightarrow$ „Ich bin auf der Suche nach einer neuen Stelle, um mein Einkommen aufzubessern.“

### Tipp für das nächste Gespräch
Konzentriere dich beim Sprechen mit „weil“ oder „obwohl“ ganz bewusst auf die **Verbposition am Satzende**. Das ist der wichtigste Schritt, um von der A2/B1-Struktur zu einem sicheren B2-Niveau zu gelangen.
```

### After: Erklärungen Deutsch
```markdown
### Was gut war
*   **Kommunikative Kompetenz:** Du hast direkt auf die Fragen geantwortet und deine Meinung (zu den Mieten und zur Arbeit) klar ausgedrückt.
*   **Struktur:** Du hast bereits komplexe Sätze mit Konjunktionen wie „aber“ und „weil“ benutzt, um Informationen zu verknüpfen.

### Wichtigste Fehler
*   ❌ „Ich wohne seit zwei Jahre in Berlin“
    *   ✅ „Ich wohne seit zwei Jahren in Berlin.“
    *   💡 Nach der Präposition „seit“ benutzt man immer den Dativ (Plural: Jahren).
*   ❌ „...weil es gibt viele Möglichkeiten“
    *   ✅ „...weil es viele Möglichkeiten gibt.“
    *   💡 In einem Nebensatz mit „weil“ muss das konjugierte Verb am Ende stehen.
*   ❌ „...weil ich brauche mehr Geld.“
    *   ✅ „...weil ich mehr Geld brauche.“
    *   💡 Auch hier ist das Verb am Ende des Nebensatzes zu platzieren.

### Besser ausdrücken
*   „Die Mieten sind zu teuer für mich.“ $\rightarrow$ „Die Mietpreise sind für mich leider zu hoch.“ (Klingt etwas idiomatischer auf B2-Niveau).
*   „Ich suche eine neue Arbeit, weil ich mehr Geld brauche.“ $\rightarrow$ „Ich suche eine neue Stelle, um mein Einkommen aufzubessern.“ (Verwendung von Infinitiv mit „um... zu“ und gehobenerem Wortschatz).

### Tipp für das nächste Gespräch
Konzentriere dich darauf, die **Verbposition in Nebensätzen** (besonders bei „weil“) zu festigen, damit deine Sätze grammatikalisch korrekt fließen.
```

## Review (Claude Code fills this in)
- **Verdict:** Accepted (2026-11-05).
- **Notes:** Diff is limited to allowed files; 118 Python + 23 JS tests and lint pass. The placeholder is replaced before the transcript (tested). An invalid `feedback_lang` falls back without raising. Lead check of the German sample: all three planted errors were found with correct corrections in both languages, and the German 💡 explanations are correct (dative after *seit*, verb-final after *weil*). Two prompt issues were passed to T016:
  - gemma emits LaTeX `$\rightarrow$`, which shows raw;
  - the ❌/✅/💡 layout varies (sibling bullets vs nested).
