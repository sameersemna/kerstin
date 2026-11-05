# T004 — Render feedback Markdown (safe, no dependency)

**Branch:** `task/T004-feedback-markdown` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
The end-of-session feedback shows as formatted text (headings, lists, bold, ✅/❌/💡 lines) instead of raw `###` and `**`. The output is safe by construction: model output can never become HTML (D017).

## Context
- `frontend/app.js`, case `feedback`: `feedbackEl.textContent = msg.markdown; // TODO(ROADMAP): render markdown`. `.feedback` in `style.css` uses `white-space: pre-wrap`.
- The model's output follows `backend/prompts/feedback.md`:
  - `###` headings;
  - `-` lists with ❌/✅/💡 items, sometimes nested by 2–4 spaces;
  - `**bold**`, `*italic*`/`_italic_` (also the server's `_Noch keine Äußerungen._`);
  - occasionally `1.` lists, `` `code` ``, `---`, `>` quotes, or a stray `####`.
- The pattern for a testable plain-script module already exists: `frontend/mic_gate.js` + `frontend/tests/mic_gate.test.js` (`node --test`, no npm).
- **D017:** no third-party renderer. A small subset parser that builds DOM nodes only via `createElement` / `createTextNode` / `textContent`, never `innerHTML`, so nothing needs sanitizing and nothing needs vendoring.

## Spec
1. **`frontend/markdown.js`** (new): a plain script, exposed via `globalThis` + `module.exports`, the same way as `mic_gate.js`.
   - `parseMarkdown(text: string) -> Block[]` is pure and has no DOM access. Blocks:
     - `{type:"heading", level:1..4, inline}` from `#`–`####`; `#####`+ is treated as level 4;
     - `{type:"list", ordered:bool, items:[{inline, children: Block[]}]}`, where `-`, `*`, `+` or `N.` start an item, an indent ≥ 2 spaces under an item nests one level (max 2 levels; deeper is flattened into level 2), and a non-indented continuation line is appended to the previous item;
     - `{type:"quote", inline}` from `>`;
     - `{type:"hr"}` from `---` / `***`;
     - `{type:"para", inline}` from consecutive plain lines joined with a space. Blank lines separate blocks.
   - Inline spans: an array of `{type:"text"|"strong"|"em"|"code", text}`, from `**x**`/`__x__`, `*x*`/`_x_` (not inside words, so `snake_case_word` stays text), and `` `x` ``. Unmatched markers stay literal text. No links, images or HTML: `[a](b)`, `<b>` and `![x](y)` render as literal text.
   - `renderMarkdown(text, doc = document) -> DocumentFragment` builds `h3`/`h4` (map levels 1–2 → `h3`, 3–4 → `h4` so feedback headings don't outsize the page), `ul`/`ol`/`li`, `blockquote`, `hr`, `p`, `strong`, `em`, `code`. It uses only `doc.createElement`, `doc.createTextNode`, `doc.createDocumentFragment`, `appendChild`.
   - Never throws: on unexpected input it falls back to one `p` with the raw text.
   - Accepts `\r\n`. Trims trailing whitespace per line.
2. **`frontend/app.js`**, case `feedback`: `feedbackEl.replaceChildren(renderMarkdown(msg.markdown))`, wrapped in try/catch with a `textContent` fallback. Remove the TODO. No other change in `app.js`.
3. **`frontend/index.html`:** include `markdown.js` before `app.js`.
4. **`frontend/style.css`:**
   - Drop `white-space: pre-wrap` from `.feedback`.
   - Add compact styles for `.feedback h3`, `h4`, `ul`, `ol`, `li`, `p`, `blockquote`, `code`, `hr`: small margins, and the existing CSS variables for colours.
5. **Tests: `frontend/tests/markdown.test.js`** (`node:test`).
   - Parser:
     - the real-shaped sample below → the expected block structure;
     - nested list;
     - ordered list;
     - continuation line;
     - `snake_case_word` and `2*3*4` stay text;
     - an unmatched `**`;
     - `_Noch keine Äußerungen._` → para with one `em`;
     - `\r\n`;
     - empty string → `[]`.
   - **Safety:**
     - `<img src=x onerror=alert(1)>`, `<script>…</script>`, `[x](javascript:alert(1))` and `![a](http://x/y.png)` all come out as `text` spans only;
     - the renderer is run against a **tiny fake document** (an object with `createElement` / `createTextNode` / `createDocumentFragment` recording calls; nodes with `appendChild` / `children`), and the test asserts that only the allowed tag names were created, no element has an `href`/`src`/`on*` property set, and `innerHTML` is never assigned (use a setter that throws).
   - Render the sample with the fake document and assert the tag tree.
   - Include this sample (modelled on real output):
     ```
     ### Was gut war
     - Du hast **flüssig** erzählt.
     - Gute Nebensätze mit *weil*.

     ### Wichtigste Fehler
     - ❌ „Ich habe gestern in die Stadt gegangen.“
       - ✅ „Ich bin gestern in die Stadt gegangen.“
       - 💡 *gehen* forms the perfect with *sein*.

     ### Tipp für das nächste Gespräch
     Benutze bewusst `obwohl`.
     ```
6. `make test` already runs every `frontend/tests/*.test.js`, so no Makefile change.

## Files allowed to change
- `frontend/markdown.js` (new), `frontend/tests/markdown.test.js` (new)
- `frontend/app.js` (feedback case only), `frontend/index.html` (script tag only), `frontend/style.css` (`.feedback` rules only)
- this task file (Worker report only)

## Out of scope
- Any third-party Markdown library or vendoring.
- Tables, links, images, raw HTML.
- Changing the feedback prompt or content (that's T016).
- Copy or save buttons.
- Server changes.

## Acceptance criteria
- [ ] `make test` (Python + JS) and `make lint` pass; the parser, safety and render tests listed above exist and pass
- [ ] `grep -n "innerHTML" frontend/markdown.js` → nothing, and the feedback path in `app.js` doesn't use `innerHTML`
- [ ] A real feedback is rendered: generate 3 real feedbacks with a throwaway, uncommitted snippet (`PromptStore.feedback_prompt()` + `OllamaLLM(Settings()).chat(..., max_tokens=1200)` on a short invented transcript with 3–4 learner errors; check `nvidia-smi` temp first, stop if ≥ 76 °C). Feed the returned `markdown` through `parseMarkdown` in Node, and paste the raw Markdown and the block summary (types + nesting) into the report. If the server shows something the parser mis-structures, fix the parser and add that shape as a test.
- [ ] `git diff main --stat` shows only allowed files

## Manual check (Sameer, after merge)
End a short conversation: the feedback shows headings, bullet lists with the ❌/✅/💡 lines indented under each error, and no `###` or `**` visible.

## Worker report (Kilo Code fills this in)
- **Changed files:** `frontend/markdown.js` (new), `frontend/tests/markdown.test.js` (new), `frontend/app.js` (feedback case only), `frontend/index.html` (script tag only), `frontend/style.css` (`.feedback` rules only), this task file.
- **How tested:** `make test` → 110 Python tests + 23 Node tests passed; `make lint` passed. Parser, real-shape, safety and fake-DOM render tests all pass. `grep -n "innerHTML" frontend/markdown.js` returns nothing; the feedback path in `app.js` uses `replaceChildren(renderMarkdown(...))` with a `textContent` fallback. The three feedbacks were generated with a throwaway heredoc (no committed script), checked with `nvidia-smi --query-gpu=temperature.gpu` before and after each call, and parsed with the Node module. Trailing hard-break spaces are trimmed by the parser.
- **Measurements (if any):** Real feedback GPU temperatures: 46→62 °C, 62→66 °C, 66→71 °C; all below the 76 °C stop threshold.
- **Deviations from spec / extra files touched:** Real feedback used indented non-bullet `✅`/`💡` continuation lines; these become child `para` blocks (max nesting remains 2 list levels), with a test added. Real feedback also nested `**...**` inside `*...*`; these are flattened to `em`/`strong`/`em` spans so no literal `**` is visible, with a test added.
- **New dependencies (+license):** None.
- **Open questions:** None.

### Real-feedback checks

#### Feedback 1 (46→62 °C)
Raw:
```markdown
### Was gut war
- Die Lernende Person verwendet korrekte Zeitformen (Präteritum und Futur I).
- Die Sätze sind klar und verständlich, mit guter Struktur.
- Sie benutzt Nebensätze (z. B. „weil ich bin sehr müde von meinem Job“) korrekt und sinnvoll.

### Wichtigste Fehler
- ❌ Original: *„weil ich bin sehr müde von meinem Job“*  
  ✅ Korrektur: *„weil ich sehr müde von meinem Job bin“*  
  💡 Die Satzstruktur im Nebensatz muss anders sein als im Hauptsatz: Verben wie „sein“ kommen am Ende.

- ❌ Original: *„obwohl ich habe kein Geld“*  
  ✅ Korrektur: *„obwohl ich kein Geld habe“*  
  💡 Im Nebensatz mit „obwohl“ steht das Verb am Ende, genauso wie bei „weil“.

### Besser ausdrücken
- „Ich habe gestern in die Stadt gegangen“ könnte klingen wie: *„Ich bin gestern in die Stadt gegangen“* – dies ist eine natürlichere Formulierung im Deutschen.
- „Ich bin sehr müde von meinem Job“ könnte klingen wie: *„Ich bin von meinem Job sehr müde“* – umgangssprachlicher und natürlicher.

### Tipp für das nächste Gespräch
Achte darauf, dass Verben im Nebensatz (z. B. nach „weil“ und „obwohl“) am Satzende stehen.
```
Blocks:
```text
heading level=3
list unordered items=3
  item children=0
  item children=0
  item children=0
heading level=3
list unordered items=1
  item children=2
    para
    para
list unordered items=1
  item children=2
    para
    para
heading level=3
list unordered items=2
  item children=0
  item children=0
heading level=3
para
```

#### Feedback 2 (62→66 °C)
Raw:
```markdown
### Was gut war
- Die Lernende Person spricht klar und verständlich.
- Sie nutzt eine Vielzahl von grammatisch korrekten Satzstrukturen.
- Sie formuliert ihre Gedanken logisch und verständlich.

### Wichtigste Fehler
- ❌ *Ich wohne seit zwei Jahre in Berlin*  
  ✅ *Ich wohne seit zwei **Jahren** in Berlin*  
  💡 Die Zahl **zwei** muss mit dem Nominativ **Jahren** konjugiert werden, nicht mit dem Akkusativ.

- ❌ *aber ich brauche mehr Geld*  
  ✅ *aber ich **brauche** mehr Geld*  
  💡 Es ist ein Satz mit **Präsens**, also korrekt. Fehler im Original nicht vorhanden.

- ❌ *weil es gibt viele Möglichkeiten*  
  ✅ *weil **es viele** Möglichkeiten gibt*  
  💡 Die Satzstruktur „weil es gibt“ ist unüblich. Stattdessen wird „weil es **viele** Möglichkeiten gibt“ verwendet.

### Besser ausdrücken
- *Ich suche eine neue Arbeit, weil ich brauche mehr Geld*  
  → *Ich suche eine neue Arbeit, weil ich **mehr Geld** brauche*

- *es gibt viele Möglichkeiten*  
  → *es **gibt viele** Möglichkeiten*

### Tipp für das nächste Gespräch
Achte darauf, dass die Zeitangaben korrekt konjugiert werden (z. B. „seit zwei Jahren“).
```
Blocks:
```text
heading level=3
list unordered items=3
  item children=0
  item children=0
  item children=0
heading level=3
list unordered items=1
  item children=2
    para
    para
list unordered items=1
  item children=2
    para
    para
list unordered items=1
  item children=2
    para
    para
heading level=3
list unordered items=1
  item children=1
    para
list unordered items=1
  item children=1
    para
heading level=3
para
```

#### Feedback 3 (66→71 °C)
Raw:
```markdown
### Was gut war
- Die lernende Person hat klar und verständlich gesprochen und sich gut in das Gespräch eingebracht.
- Sie nutzt korrekt Vergangenheitsformen und Nebensätze (z. B. „weil sie mag Komödien“).
- Die Aussagen sind logisch und folgen einer klaren Erzählstruktur.

### Wichtigste Fehler
- ❌ Original: *„obwohl die Geschichte war ein bisschen langsam“*  
  ✅ Korrektur: *„obwohl die Geschichte ein bisschen langsam war“*  
  💡 The correct word order in a subordinate clause with „obwohl“ requires the verb to be at the end.

- ❌ Original: *„weil sie mag Komödien“*  
  ✅ Korrektur: *„weil sie Komödien mag“*  
  💡 In a subordinate clause introduced by „weil“, the verb comes at the end.

- ❌ Original: *„Meine Schwester hat den Film besser gefunden als ich“*  
  ✅ Korrektur: *„Meine Schwester hat den Film besser gefunden als ich ihn“*  
  💡 When comparing with „als“, the pronoun „ihn“ should be used for clarity.

### Besser ausdrücken
- „Die Geschichte war ein bisschen langsam“ klingt natürlicher als „die Geschichte war ein bisschen langsam“.
- „Wir haben viel gelacht“ könnte auch als „wir haben viel gelacht und uns gut unterhalten“ formuliert werden, um die Beschreibung zu bereichern.

### Tipp für das nächste Gespräch
Achte besonders auf die Satzstruktur in Nebensätzen (z. B. mit „obwohl“, „weil“ und „als“), insbesondere auf die Position des Verbs am Satzende.
```
Blocks:
```text
heading level=3
list unordered items=3
  item children=0
  item children=0
  item children=0
heading level=3
list unordered items=1
  item children=2
    para
    para
list unordered items=1
  item children=2
    para
    para
list unordered items=1
  item children=2
    para
    para
heading level=3
list unordered items=2
  item children=0
  item children=0
heading level=3
para
```

## Review (Claude Code fills this in)
- **Verdict:**
- **Notes:**
