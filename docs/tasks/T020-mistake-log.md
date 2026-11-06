# T020 — Mistake log (opt-in, local, categories only)

**Branch:** `task/T020-mistake-log` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
If the learner opts in, each feedback's mistakes are recorded **as grammar categories** (e.g. "Verbposition", "Kasus") in a local SQLite file. The UI shows "Deine Schwerpunkte" (counts per category over the last 90 days) and has a button that deletes everything. T024 will use the summary to steer future conversations. **No learner text is stored** (D020).

## Context
- **Privacy (CLAUDE.md):** nothing on disk by default, transcripts only in memory, and opt-in storage only through a task. Since D020 we store only `(session date, scenario, feedback language, category)`. The ❌/✅/💡 texts are never written. There's no auth yet (D010, T040), and the server may be reachable on the LAN, which is another reason to keep no text.
- **Parsing:** `feedback_checks.parse_errors(markdown) -> tuple[FeedbackError(quote, correction, explanation)]` already handles both real layouts (T016). Reuse it; don't write a second parser.
- **Categories:** the same as the T016 fixtures: `verbposition`, `kasus`, `praeposition`, `adjektivendung`, `perfekt_hilfsverb`, `genus`, `wortwahl`, `sonstiges`. The feedback doesn't label its items, so we classify the 💡 explanation (EN or DE, T017) with keyword rules. That costs no GPU and is deterministic.
- `sqlite3` is in the standard library, so there's no new dependency. File I/O goes through `asyncio.to_thread`.

## Spec
1. **`backend/kerstin/mistakes.py`** (new):
   - `CATEGORIES: dict[str, str]`, key → German UI label: Verbposition · Kasus · Präpositionen · Adjektivendungen · Perfekt mit sein/haben · Genus (Artikel) · Wortwahl · Sonstiges.
   - **`classify(error: FeedbackError) -> str`**, a pure function. Lower-case the explanation (falling back to quote+correction), then apply rules in this **priority order**; the first match wins:
     1. `perfekt_hilfsverb`: (perfect|perfekt|auxiliary|hilfsverb) **and** (sein|haben|movement|bewegung);
     2. `verbposition`: (word order|wortstellung|verb position|verbposition|subordinate|nebensatz|end of the (sentence|clause)|am ende|second position|zweite(n)? position|position 2);
     3. `adjektivendung`: (adjective|adjektiv) and (ending|endung);
     4. `kasus`: (dative|dativ|accusative|akkusativ|genitive|genitiv|case|kasus);
     5. `genus`: (masculine|feminine|neuter|maskulin|feminin|neutrum|gender|genus);
     6. `praeposition`: (preposition|präposition);
     7. `wortwahl`: (word choice|wortwahl|wrong word|falsches wort|idiomatic|idiomatisch|meaning|bedeutung);
     8. else `sonstiges`.

     Adjust the keywords only if a real explanation from the corpus below is misclassified, and say so in the report.
   - **`MistakeLog(path: Path, max_days: int = 180)`:**
     - `async record(scenario: str, lang: str, categories: list[str]) -> int` inserts one session row and N mistake rows in a transaction, prunes rows older than `max_days`, and returns N;
     - `async summary(days: int = 90) -> dict` returns `{"sessions": int, "categories": [{"key","label","count"}]}`, sorted by count desc, only count > 0;
     - `async clear() -> None` deletes all rows **and** `VACUUM`s, so deleted data doesn't linger in the file.
     - Schema: `sessions(id INTEGER PK, created_at TEXT UTC ISO, scenario TEXT, lang TEXT)`, `mistakes(session_id INTEGER REFERENCES sessions ON DELETE CASCADE, category TEXT)`.
     - Create the parent dir and the tables lazily on first write. **Don't create the file on startup or on read**: if the file doesn't exist, `summary()` returns zeros without creating it.
     - **There is no column for learner text, and none may be added.**
2. **Config:**
   - `mistake_log_path: Path = PROJECT_DIR / "data" / "mistakes.sqlite3"`;
   - `mistake_log_enabled: bool = True` (the server *allows* the log; the learner opts in in the UI);
   - `mistake_log_max_days: int = 180`.

   Add them to `.env.example`, and add `data/` to `.gitignore`.
3. **Session/protocol:**
   - `end` gains an optional `save_mistakes: bool` (default false).
   - In `Session.feedback(lang, save_mistakes=False)`: after the `feedback` message is sent, if `save_mistakes` and the log is enabled (`Deps.mistakes: MistakeLog | None`), classify `parse_errors(markdown)` and `record()` them, then send `{"type":"mistakes_saved","count":N}`.
   - On a DB error: log a WARNING with the exception type only, send `{"type":"mistakes_saved","count":0,"error":"failed"}`, and the feedback is unaffected.
   - Not recorded when: the feedback was the thermal path, there were no learner lines ("_Noch keine Äußerungen._"), or there are zero parsed errors. In the last case, still record the session row with N = 0, so "sessions" counts practice.
   - Log `mistakes saved (n=…)` at INFO, with no text.
4. **HTTP API** (`main.py`):
   - `GET /api/mistakes` → `{"enabled": bool, "sessions": n, "categories": [...]}`;
   - `DELETE /api/mistakes` → `{"cleared": true}`;
   - when disabled, GET returns `enabled:false` and DELETE returns 404.
   - Document both endpoints and `mistakes_saved` in `docs/PROTOCOL.md`.
5. **UI:**
   - `index.html` gets a small aside box **"Deine Schwerpunkte"**:
     - a checkbox `#saveMistakes` "Fehler-Kategorien speichern (lokal, ohne deine Sätze)", **default off**, remembered in `localStorage` (try/catch);
     - a list `#mistakeSummary` (e.g. "Verbposition · 7");
     - a button `#clearMistakes` "Alle löschen".
     - The box is hidden when the server says `enabled:false`.
   - `app.js`:
     - `end` sends `save_mistakes` from the checkbox;
     - load `GET /api/mistakes` on page load and after `mistakes_saved`;
     - "Alle löschen" asks for confirmation **inside the page**: the button changes to "Wirklich löschen?" for 5 s, and a second click sends `DELETE`. No `confirm()`.
     - Render the list with `textContent` only.
   - Minimal CSS, consistent with the hint box.
6. **Tests:**
   - `backend/tests/test_mistakes.py` (new):
     - **classifier corpus:** at least 24 real 💡 lines copied from the T016/T011/T017 reports (`docs/tasks/T016-feedback-quality.md`, `T011-feedback-model.md`, `T017-feedback-language.md`), EN and DE, each with the expected category from the planted error it belongs to. **All must classify correctly.** Also include 3 made-up "wortwahl"/"sonstiges" lines.
     - **store** (tmp path): record → summary counts and order; days filter (inject a clock or set `created_at`); `max_days` pruning; `clear()` empties and the file stays valid; `summary()` on a missing file → zeros, and the file is **not** created; the schema has no text column (inspect `PRAGMA table_info`).
   - `backend/tests/test_session.py`:
     - `save_mistakes=True` → `record` called with the classified categories + a `mistakes_saved` message;
     - `False` → no `record`;
     - DB error → `error:"failed"` and the feedback is still sent;
     - thermal → no record.
   - API tests (new `backend/tests/test_api_mistakes.py`, FastAPI `TestClient` or httpx ASGI transport, tmp path): GET when empty, GET after record, DELETE, disabled → 404.

## Files allowed to change
- `backend/kerstin/mistakes.py` (new), `backend/kerstin/config.py`, `backend/kerstin/session.py` (`feedback()` + `Deps.mistakes`), `backend/kerstin/main.py` (wiring, `end` arg, 2 endpoints)
- `backend/tests/test_mistakes.py` (new), `backend/tests/test_api_mistakes.py` (new), `backend/tests/test_session.py`
- `frontend/index.html`, `frontend/app.js` (mistake box + `end` field only), `frontend/style.css` (box only)
- `docs/PROTOCOL.md`, `.env.example`, `.gitignore` (`data/` only; leave the pre-existing `*.prs` line as it is)
- this task file (Worker report only)

This is 14 files. Storage, protocol and UI form one opt-in feature (lead-approved).

## Out of scope
- Steering the conversation (T024).
- Storing any learner text or the feedback.
- A history page (T023).
- Multi-user / auth (T040).
- An LLM-based classifier.
- Changing `feedback.md`.

## Acceptance criteria
- [ ] `make test` (Python + JS) and `make lint` pass; the tests listed above exist; the classifier corpus is 100 % correct
- [ ] With the checkbox off (the default), nothing is written: after a session, `data/` doesn't exist. Show it.
- [ ] With it on: a real session on port 8771 (or a scripted `end` with `save_mistakes:true` after 2 learner turns with errors) creates the file. `sqlite3 data/mistakes.sqlite3 .schema` and `SELECT * FROM mistakes` are pasted and show categories only. Then `DELETE /api/mistakes` → the summary is empty. Use a temporary `KERSTIN_MISTAKE_LOG_PATH` under `/tmp`, and remove it afterwards.
- [ ] `git diff main --stat` shows only allowed files

## Manual check (Sameer, after merge)
Tick "Fehler-Kategorien speichern", have a short conversation with a deliberate *weil … Verb* mistake, and press "Beenden & Feedback". "Deine Schwerpunkte" shows "Verbposition · 1". Then "Alle löschen" → click again → the list is empty.

## Worker report (Kilo Code fills this in)
- **Changed files:** `backend/kerstin/mistakes.py` (new), `backend/kerstin/config.py`, `backend/kerstin/session.py`, `backend/kerstin/main.py`, `backend/tests/test_mistakes.py` (new), `backend/tests/test_api_mistakes.py` (new), `backend/tests/test_session.py`, `frontend/index.html`, `frontend/app.js`, `frontend/style.css`, `docs/PROTOCOL.md`, `.env.example`, `.gitignore` (`data/` only), and this task file.
- **How tested:** `make test` → **194 Python + 23 Node** tests passed; `make lint` passed; `node --check frontend/app.js` passed. New tests cover the 30-line real classifier corpus (plus 6 made-up `wortwahl`/`sonstiges` lines), record/summary/order/days/pruning/clear/schema/lazy-file behavior, the session opt-in/opt-out/DB-error/thermal/no-learner-lines paths, and the enabled/disabled HTTP API.
- **Measurements (if any):**
  - **Classifier:** 30 real 💡 lines (EN + DE) from the T016/T011/T017 reports plus 6 made-up lines → **100%** expected categories. The only keyword adjustment: bare `am Ende` now needs sentence/verb context (`Satz|Verb|Nebensatz|Clause`); the real T016 explanation *„… deshalb muss am Ende ein ‚n‘ an ‚Fahrräder‘ stehen“* is about a noun ending and was otherwise misclassified as Verbposition.
  - **Off (default):** scripted `Session.feedback(save_mistakes=False)` with a temp path printed:
    ```text
    path exists: False
    parent exists: False
    mistakes_saved: []
    project data exists: False
    ```
  - **On:** scripted `end` after two learner turns with a dative error and a subordinate-clause verb-order error; `KERSTIN_MISTAKE_LOG_PATH=/tmp/kilo/t020-on/mistakes.sqlite3`; `mistakes_saved` was `{"count": 2}`; summary was `{"sessions": 1, "categories": [{"key": "kasus", "label": "Kasus", "count": 1}, {"key": "verbposition", "label": "Verbposition", "count": 1}]}`.
  - **Schema (pasted):**
    ```sql
    CREATE TABLE sessions (
                    id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    scenario TEXT NOT NULL,
                    lang TEXT NOT NULL
                );
    CREATE TABLE mistakes (
                    session_id INTEGER NOT NULL
                        REFERENCES sessions(id) ON DELETE CASCADE,
                    category TEXT NOT NULL
                );
    ```
  - **Rows (pasted):**
    ```text
    session_id  category
    ----------  ----------
    1           kasus
    1           verbposition
    ```
    The session row is `2026-11-06T08:59:08+00:00 | freies_gespraech | en`; no learner sentence, correction or explanation is stored.
  - **Delete:** `GET /api/mistakes` before DELETE had 1 session and the two categories; `DELETE /api/mistakes` → `{"cleared": true}`; the next GET was `{"enabled": true, "sessions": 0, "categories": []}`. The temp DB and its `/tmp` directory were removed. No server was started, so port 8771/8770 was untouched.
- **Deviations from spec / extra files touched:** The classifier keyword refinement above is the only spec deviation. The pre-existing `.gitignore` `*.prs` line was left as is; this task added `data/`. `sqlite3` is stdlib, so no dependency change.
- **New dependencies (+license):** None.
- **Open questions:** None. The browser manual check remains for Sameer after merge.

## Review (Claude Code fills this in)
- **Verdict:** Accepted with two lead one-liners (2026-11-06).
- **Notes:**
  - **Privacy as specified:**
    - the schema has no text column;
    - `summary()` opens read-only and never creates the file;
    - nothing is written unless `save_mistakes`;
    - "Alle löschen" deletes and VACUUMs;
    - the 180-day prune cascades (foreign keys on);
    - logs contain counts and exception types only.
  - "Off writes nothing" was shown. 194 Python + 23 JS tests and lint pass.
  - **Lead fix 1:** the classifier missed a real T016 explanation, „Meiner Meinung nach occupies the first position, so the verb must follow immediately“ → `sonstiges`. Added an inversion rule (first/erste position|Stelle + verb → `verbposition`) and put the line in the corpus (now 31 real lines).
  - **Lead fix 2:** `save_mistakes` is parsed as `data.get("save_mistakes") is True`. Before, `bool()` turned the string `"false"` into an opt-in.
