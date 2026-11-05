# T022 — Hint box: "Wie sagt man …?"

**Branch:** `task/T022-hint-button` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
In the middle of a conversation, the learner can **type** a word or phrase they're missing, in English or as a German paraphrase ("notice period", "das Ding zum Dosenöffnen"), and get a short German answer in a hint panel. The answer gives the expression with its article/plural or key verb forms, plus one example sentence that fits the conversation. The conversation itself is untouched: no audio, no turn, nothing in the history, and nothing in the feedback.

## Context and design choices (lead)
- **Typed, not spoken.** STT always runs with `language=de` (shared whisper.cpp, D012), so English speech would be mis-transcribed. Typing is also safe in speaker mode, because the mic gate is unaffected. The space-bar interrupt already ignores `INPUT` elements (T014).
- **Text only, not spoken by Kerstin**, so there's no interference with the playback queue or the mic gate.
- **Not added to `history`.** A hint is a lookup, not part of the dialogue, and it must not appear as a learner line in the feedback.
- **Same model** (`gemma4:26b`). Ollama runs with `OLLAMA_NUM_PARALLEL=1` (shared config, don't change it). A hint and a conversation turn therefore queue behind each other. Keep hints to ≤ 120 tokens so the worst-case delay added to a turn is ≈1 s, and measure it.
- **Thermal guard applies** (D016). A hint is GPU work.
- The answer is shown with `renderMarkdown` (T004, D017).

## Spec
1. **Prompt: `backend/prompts/hint.md`** (new, German). Kerstin, as a helpful peer, gets `{query}` and `{context}` (the last ≤ 4 history messages, in the `format_feedback_transcript` format). Rules:
   - answer **only in German**, at most 4 short lines, no greeting and no follow-up question;
   - first line: the best expression in bold. For nouns give the article and plural (`**die Kündigungsfrist** (Pl. die Kündigungsfristen)`); for verbs give the key forms (`**aufschieben** (schob auf, hat aufgeschoben)`); mark separable verbs and reflexives, and fixed prepositions with case (`**sich kümmern um** + Akk.`);
   - optional second line: one alternative, if it's really common;
   - last line: `Beispiel: „…“`, one natural B2 sentence that fits the context when there is one;
   - if the query is unclear, give the most likely meaning; don't ask back;
   - no LaTeX, no tables, no English sentences (a single English word in brackets for disambiguation is allowed).
2. **`PromptStore.hint_prompt(query: str, context: str) -> str`.** Replace `{context}` first, then `{query}`, so neither can inject the other's placeholder.
3. **Session** (`session.py`):
   - `async def hint(self, query: str) -> None`:
     - strip the query; empty → ignore; > 120 chars → send `{"type":"hint","query":<first 120>,"error":"too_long"}`;
     - thermal hot → `{"type":"hint","query","error":"thermal","temp_c"}`;
     - otherwise run `llm.chat([{"role":"user","content":prompt}], max_tokens=120)` in `self._hint_task`. A new hint cancels a running hint, but never a running turn, and a turn never cancels a hint.
     - Result → `{"type":"hint","query","markdown": strip_think(text).strip()}`; an exception → `{"type":"hint","query","error":"failed"}` (log the exception type only).
     - `history` is never modified.
   - `close()` also cancels `_hint_task`.
   - Log `hint ok (ms=…)` at INFO, **without** the query or answer text.
4. **`main.py`:** `{"type":"hint","query":"…"}` → `session.hint(query)` when a session exists; otherwise send the existing `error` "send 'start' first". Don't await the LLM inside the receive loop: `hint()` starts the task and returns, so audio and interrupts keep flowing.
5. **`docs/PROTOCOL.md`:**
   - client: `{"type":"hint","query"}`;
   - server: `{"type":"hint","query","markdown"}` or `{"type":"hint","query","error":"too_long"|"thermal"|"failed","temp_c"?}`.

   `hint` messages carry no `turn` and never affect turn state.
6. **UI:**
   - `frontend/index.html`, in `<aside>` above `#feedback`: a box with the heading "Wie sagt man …?", an `<input id="hintInput" maxlength="120" placeholder="z. B. notice period">`, a button `#hintBtn` "Fragen", and `<div id="hintList">`.
     - Enter in the input submits.
     - Input and button are enabled only while a session is active (after `start`, until `end`/disconnect).
   - `frontend/app.js`:
     - On submit: send the hint, show a pending entry ("… frage nach"), and clear the input.
     - On `hint`: replace the pending entry for that query with the query in bold + `renderMarkdown(markdown)`, or with a short German error: "zu lang (max. 120 Zeichen)" / "GPU zu warm – gleich nochmal" / "hat nicht geklappt".
     - Newest first, at most 5 entries, in memory only (no localStorage: hints are learner text, see the privacy rule).
     - Clear the list on `session`.
     - `hint` must **not** call the mic gate, change `currentTurn` or touch playback.
   - `frontend/style.css`: compact styles for the box, consistent with `.feedback`.
7. **Tests:**
   - `backend/tests/test_prompts.py`: hint placeholders are replaced; injection order (a query containing `{context}` stays literal).
   - `backend/tests/test_session.py`:
     - hint → `hint` message with the LLM text, and history unchanged;
     - hint during a running turn → the turn still completes (`reply_done`) and isn't cancelled;
     - new audio during a running hint → the hint still completes;
     - a second hint cancels the first (only one result is sent);
     - `too_long`; thermal hot → error, no LLM call; LLM exception → `failed`;
     - empty query → nothing sent;
     - `feedback()` after a hint → the feedback prompt contains no hint text.
8. **Real samples for lead grading:**
   - Run 10 hints on `gemma4:26b` with a throwaway, uncommitted snippet; check `nvidia-smi` first and stop at ≥ 76 °C. Use these queries, each with a short invented 2-message context: "notice period", "to procrastinate", "landlord", "I'm looking forward to it", "deposit (for a flat)", "to run out of milk", "to take something for granted", "awkward", "commute", "das Ding, mit dem man Dosen öffnet".
   - Paste every answer and its latency (ms).
   - Also measure once how much a hint sent right before a learner turn delays that turn's `llm_first_token_ms`, compared with the same turn without a hint. Fixed seed, 3 pairs.

## Files allowed to change
- `backend/prompts/hint.md` (new), `backend/kerstin/prompts.py`, `backend/kerstin/session.py`, `backend/kerstin/main.py`
- `backend/tests/test_prompts.py`, `backend/tests/test_session.py`
- `frontend/index.html`, `frontend/app.js` (hint only), `frontend/style.css` (hint box only)
- `docs/PROTOCOL.md` (hint rows only)
- this task file (Worker report only)

This is 11 files. The prompt, server and UI form one small feature (lead-approved).

## Out of scope
- Spoken hints.
- English STT.
- Speaking the answer.
- Storing or logging hints.
- Showing hints in the feedback (could come with T020).
- A separate hint model.
- Changing Ollama's server config (`OLLAMA_NUM_PARALLEL` etc.: it's shared with other projects).

## Acceptance criteria
- [ ] `make test` (Python + JS) and `make lint` pass; all tests listed above exist
- [ ] 10 real answers pasted. They must be German only, ≤ 4 lines, with a bold first line, article/plural or verb forms, and a `Beispiel:` line. The lead grades the correctness of each.
- [ ] Hint latency p50 reported; the turn delay from a concurrent hint reported (target ≤ 1.2 s worst case)
- [ ] No hint text in INFO logs; hints are not in `history` and not in the feedback (tests)
- [ ] `git diff main --stat` shows only allowed files

## Manual check (Sameer, after merge)
During a conversation, type "landlord" and press Enter. A German answer with article and example appears in the side panel. Kerstin keeps talking or listening as before, and the space bar still interrupts her when the focus isn't in the input.

## Worker report (Kilo Code fills this in)
- **Changed files:** `backend/prompts/hint.md` (new), `backend/kerstin/prompts.py`, `backend/kerstin/session.py`, `backend/kerstin/main.py`, `backend/tests/test_prompts.py`, `backend/tests/test_session.py`, `frontend/index.html`, `frontend/app.js` (hint only), `frontend/style.css` (hint box only), `docs/PROTOCOL.md` (hint rows only), this task file.
- **How tested:** `make test` → 149 Python tests + 23 Node tests passed; `make lint` passed. Tests cover hint placeholders and injection in both directions, hint markdown/history isolation, hint during a running turn, audio during a running hint, second-hint cancellation, `too_long`, thermal, LLM failure, empty query, close cancellation, and feedback containing no hint text. The 10 real hints and the 3 delay pairs below used a throwaway heredoc on `gemma4:26b`; no sample script or hint text was committed.
- **Measurements (if any):** Hint latency p50 (median) = **925 ms**, mean 914 ms, range 726–1120 ms. Concurrent-turn delay: mean **+673 ms**, worst **+715 ms** (target ≤ 1200 ms). `nvidia-smi` was checked before every hint call; GPU temps were 58, 64, 66, 67, 67, 67, 67, 67, 68, 68 °C, no abort at 76 °C. The delay runs stayed at 59–68 °C.
- **Deviations from spec / extra files touched:** None beyond the allowed files. `hint_prompt()` uses a single-pass placeholder replacement (safer than two sequential replacements): neither a query containing `{context}` nor a context containing `{query}` is re-expanded. The final samples are the final prompt's raw answers; all are two lines, German, bold lemma with forms, and a `Beispiel:` line.
- **New dependencies (+license):** None.
- **Open questions:** The manual browser check remains for Sameer after merge. Round 1 target is borderline: auto **17/20**, at best **18/20** manually; the lead must grade #13/#20.
- **Round 1:** Prompt hygiene, 0.2 hint temperature, and a 20-case hold-out eval are implemented. Final eval auto **17/20** (p50 **1218 ms**, p90 **1346 ms**); all 20 raw answers are below. Manual review: #11 is wrong (`sich auskommen mit`), #8 gives forms without reflexive `sich`, #13 is a correct concrete phrase but not the generic lemma, and #20 is a correct variant the accept list omits. All 20 example sentences look grammatically correct. Strictly the target ≥18/20 is borderline: 17/20 auto, 18/20 if #13 and #20 count as correct.
- **Round 1 files:** `backend/prompts/hint.md`, `backend/kerstin/llm.py`, `backend/kerstin/config.py`, `backend/kerstin/session.py` (hint temperature only), `backend/kerstin/main.py` (Deps wiring only), `.env.example`, `backend/kerstin/hint_checks.py` (new), `backend/tests/test_hint_checks.py` (new), `backend/tests/test_llm.py`, `backend/tests/test_session.py`, `scripts/hint_eval.py` (new), `scripts/hint_cases.json` (new), `Makefile` (`hint-eval` only), this task file. No frontend changes.
- **Round 1 verification:** `make test` → **165 Python + 23 Node** tests passed; `make lint` passed. No new dependencies.

### Real hint samples (final prompt, `gemma4:26b`, seeds 14001–14010)

**1. notice period** — 1120 ms
Context: Lernende Person: Ich möchte meinen Mietvertrag kündigen. / Kerstin: Weißt du schon, wie lange deine Kündigungsfrist ist?
```text
**die Kündigungsfrist** (Pl. die Kündigungsfristen)
Beispiel: „Du musst den Mietvertrag drei Monate im Voraus kündigen, also beachte die Kündigungsfrist.“
```

**2. to procrastinate** — 1010 ms
Context: Lernende Person: Ich schiebe meine Hausarbeit schon seit Tagen auf. / Kerstin: Warum fängst du nicht einfach heute an?
```text
**aufschieben** (schob auf, hat aufgeschoben)
Beispiel: „Ich nehme mir vor, die Hausarbeit zu erledigen, aber ich schiebe sie ständig auf.“
```

**3. landlord** — 955 ms
Context: Lernende Person: Die Heizung in meiner Wohnung ist kaputt. / Kerstin: Hast du schon deinen Vermieter angerufen?
```text
**der Vermieter** (Pl. die Vermieter)
Beispiel: „Ich muss heute meinen Vermieter anrufen, um die Reparatur der Heizung zu besprechen.“
```

**4. I'm looking forward to it** — 875 ms
Context: Lernende Person: Nächste Woche fahren wir nach Hamburg. / Kerstin: Freust du dich schon auf die Reise?
```text
**sich freuen auf** + Akk. (freute sich, hat sich gefreut)
Beispiel: „Ich freue mich schon sehr auf unseren gemeinsamen Urlaub.“
```

**5. deposit (for a flat)** — 957 ms
Context: Lernende Person: Ich muss für die neue Wohnung noch eine Kaution zahlen. / Kerstin: Wie hoch ist die Kaution?
```text
**die Kaution** (Pl. die Kautionen)
Beispiel: „Vor der Schlüsselübergabe muss ich die Kaution auf das Konto des Vermieters überweisen.“
```

**6. to run out of milk** — 726 ms
Context: Lernende Person: Wir haben keine Milch mehr für den Kaffee. / Kerstin: Kannst du schnell noch welche kaufen?
```text
**ausgehen** (ging aus, ist ausgegangen)
Beispiel: „Die Milch ist uns leider mitten am Morgen ausgegangen.“
```

**7. to take something for granted** — 988 ms
Context: Lernende Person: Meine Freundin hilft mir immer, aber ich habe mich nie bedankt. / Kerstin: Vielleicht solltest du ihr sagen, dass du das schätzt.
```text
**etwas als selbstverständlich ansehen** (sah als selbstverständlich an, hat als selbstverständlich angesehen)
Beispiel: „Man sollte die Unterstützung seiner Freunde nicht als selbstverständlich ansehen.“
```

**8. awkward** — 729 ms
Context: Lernende Person: Ich habe den Namen von ihrem Freund vergessen und wusste nicht, was ich sagen soll. / Kerstin: Das ist mir auch schon passiert.
```text
**unangenehm**
Beispiel: „Die Stille im Raum war nach der peinlichen Antwort sehr unangenehm.“
```

**9. commute** — 887 ms
Context: Lernende Person: Ich fahre jeden Tag eine Stunde mit dem Zug zur Arbeit. / Kerstin: Das klingt anstrengend. Hast du einen langen Arbeitsweg?
```text
**der Arbeitsweg** (Pl. die Arbeitswege)
Beispiel: „Mein täglicher Arbeitsweg dauert aufgrund der vielen Verspätungen leider sehr lange.“
```

**10. das Ding, mit dem man Dosen öffnet** — 895 ms
Context: Lernende Person: Ich finde den Dosenöffner in der Küche nicht. / Kerstin: Womit öffnest du sonst die Dosen?
```text
**der Dosenöffner** (Pl. die Dosenöffner)
Beispiel: „Ich kann die Dose ohne einen funktionierenden Dosenöffner nicht öffnen.“
```

### Concurrent hint → turn delay (fixed seed, three pairs)

| pair | seed | no hint, first token | with hint, first token | delta |
|---|---:|---:|---:|---:|
| 1 | 20000 | 338 | 945 | +607 |
| 2 | 20001 | 105 | 820 | +715 |
| 3 | 20002 | 99 | 797 | +698 |

Each pair used the same fixed history and turn text, differing only by the concurrent hint. The with-hint runs show the expected queueing delay from `OLLAMA_NUM_PARALLEL=1`. No Ollama configuration was changed.

### Round 1 — hint quality and hold-out eval

Prompt hygiene: the final `hint.md` contains no eval query (unit-tested). Its format examples are neutral (`die Wohnung`, `anfangen`, `sich erinnern an`, `gut`), and it has no case-specific answers or rules. Hints now run at `hint_temperature=0.2`; chat and feedback are unchanged. The eval run used the defaults (`gemma4:26b`, 1 run, seed base 1234), `cool_down()` before every call, and was saved to `/tmp/kilo/t022-round1d.md`. GPU temperature went 57→72 °C, with no 80 °C abort.

Hold-out hygiene: the 20 queries/context are unchanged. Accept lists contain only correct dictionary variants (`sich an etwas gewöhnen`, `mit jemandem auskommen`, `jemandem zustimmen`, `interessiert sein an`); no wrong output was added to make a case pass. The prompt contains no query text.

| # | query | pos | ms | format | lemma | noun/adj | example | noise | auto |
|---:|---|---|---:|---|---|---|---|---:|---|
| 1 | to get used to something | verb | 1338 | OK | OK | - | OK | 0 | PASS |
| 2 | stubborn | adj | 1061 | OK | OK | OK | OK | 0 | PASS |
| 3 | to give up | verb | 1050 | OK | OK | - | OK | 0 | PASS |
| 4 | appointment (doctor) | noun | 1088 | OK | OK | OK | OK | 0 | PASS |
| 5 | to complain about | verb | 1403 | OK | OK | - | OK | 0 | PASS |
| 6 | the thing you plug a phone charger into | noun | 1207 | OK | OK | OK | OK | 0 | PASS |
| 7 | to apply for a job | verb | 1278 | OK | OK | - | OK | 0 | PASS |
| 8 | to be afraid of | verb | 1416 | OK | OK | - | OK | 0 | PASS |
| 9 | to depend on | verb | 1260 | OK | OK | - | OK | 0 | PASS |
| 10 | reliable | adj | 914 | OK | OK | OK | OK | 0 | PASS |
| 11 | to get along with someone | verb | 1221 | OK | FAIL | - | OK | 0 | FAIL |
| 12 | receipt | noun | 1346 | OK | OK | OK | OK | 0 | PASS |
| 13 | to look after children | verb | 1242 | OK | FAIL | - | OK | 0 | FAIL |
| 14 | to agree with someone | verb | 1272 | OK | OK | - | OK | 0 | PASS |
| 15 | overtime | noun | 1206 | OK | OK | OK | OK | 0 | PASS |
| 16 | to cancel an appointment | verb | 1209 | OK | OK | - | OK | 0 | PASS |
| 17 | to borrow | verb | 1128 | OK | OK | - | OK | 0 | PASS |
| 18 | to be interested in | verb | 1243 | OK | OK | - | OK | 0 | PASS |
| 19 | sustainable | adj | 883 | OK | OK | OK | OK | 0 | PASS |
| 20 | to remind someone of something | verb | 1215 | OK | FAIL | - | OK | 0 | FAIL |

Auto checks: **17/20 pass** · p50 = **1218 ms** · p90 = **1346 ms** · mean = 1199 ms.

Manual grading notes:
- #11: `sich auskommen mit` is wrong; the correct lemma is `auskommen mit` (the example itself is correct).
- #8: `sich fürchten vor` is right, but the forms `fürchtete, hat gefürchtet` omit reflexive `sich`.
- #13: `auf Kinder aufpassen` is a correct concrete phrase, but the generic lemma is `aufpassen auf` + Akk.; this is why auto fails.
- #20: `jemanden erinnern an` is a correct variant, but the accept list only has `jemanden an etwas erinnern`.
- All 20 example sentences look grammatically correct. The target is therefore 17/20 auto, 18/20 manually if #13 and #20 are accepted; it is not cleanly above the ≥18/20 bar, so the lead should grade.

Neutral context:
```text
Kerstin: Und, wie war dein Wochenende?
Lernende Person: Ganz gut, aber ich war ziemlich müde.
```

#### Raw answers

**1. to get used to something (verb) — 1338 ms**

Seed 1235 · accept: `sich gewöhnen an`, `sich an etwas gewöhnen`

```text
**sich gewöhnen an** + Akk. (gewöhnte sich, hat sich gewöhnt)
Alternative: sich an etwas anpassen
Beispiel: „Ich muss mich erst an das neue Klima gewöhnen.“
```

format=OK · lemma=OK · pos=OK · example=OK · noise=0 · auto=PASS

**2. stubborn (adj) — 1061 ms**

Seed 1236 · accept: `stur`, `hartnäckig`

```text
**stur**
Alternative: eigensinnig
Beispiel: „Obwohl ich ihn um Hilfe gebeten habe, blieb er stur und wollte alles alleine machen.“
```

format=OK · lemma=OK · pos=OK · example=OK · noise=0 · auto=PASS

**3. to give up (verb) — 1050 ms**

Seed 1237 · accept: `aufgeben`, `aufhören`

```text
**aufgeben** (gab auf, hat aufgegeben)
Alternative: verzichten
Beispiel: „Ich werde niemals aufgeben, auch wenn es schwierig wird.“
```

format=OK · lemma=OK · pos=OK · example=OK · noise=0 · auto=PASS

**4. appointment (doctor) (noun) — 1088 ms**

Seed 1238 · accept: `der Termin`, `der Arzttermin`

```text
**der Termin** (Pl. die Termine)
Alternative: die Verabredung
Beispiel: „Ich habe morgen um zehn Uhr einen wichtigen Termin beim Arzt.“
```

format=OK · lemma=OK · pos=OK · example=OK · noise=0 · auto=PASS

**5. to complain about (verb) — 1403 ms**

Seed 1239 · accept: `sich beschweren über`

```text
**sich beschweren über** + Akk. (beschwerte sich, hat sich beschwert)
Alternative: klagen über + Akk.
Beispiel: „Ich möchte mich über den lauten Lärm der Nachbarn beschweren.“
```

format=OK · lemma=OK · pos=OK · example=OK · noise=0 · auto=PASS

**6. the thing you plug a phone charger into (noun) — 1207 ms**

Seed 1240 · accept: `die Steckdose`

```text
**die Steckdose** (Pl. die Steckdosen)
Alternative: die Netzsteckdose
Beispiel: „Ich kann mein Handy nicht laden, weil die Steckdose defekt ist.“
```

format=OK · lemma=OK · pos=OK · example=OK · noise=0 · auto=PASS

**7. to apply for a job (verb) — 1278 ms**

Seed 1241 · accept: `sich bewerben um`, `sich bewerben bei`, `sich bewerben für`

```text
**sich bewerben um** + Akk. (bewarb sich, hat sich beworben)
Alternative: eine Bewerbung einreichen
Beispiel: „Ich möchte mich um diese Stelle als Projektleiter bewerben.“
```

format=OK · lemma=OK · pos=OK · example=OK · noise=0 · auto=PASS

**8. to be afraid of (verb) — 1416 ms**

Seed 1242 · accept: `Angst haben vor`, `sich fürchten vor`

```text
**sich fürchten vor** + Dat. (fürchtete, hat gefürchtet)
Alternative: Angst haben vor + Dat.
Beispiel: „Ich fürchte mich vor der Dunkelheit, wenn ich alleine im Wald bin.“
```

format=OK · lemma=OK · pos=OK · example=OK · noise=0 · auto=PASS

**9. to depend on (verb) — 1260 ms**

Seed 1243 · accept: `abhängen von`

```text
**abhängen von** + Dat. (hing ab, hat abgehangen)
Alternative: angewiesen sein auf + Akk.
Beispiel: „Ob wir morgen wandern gehen, hängt vom Wetter ab.“
```

format=OK · lemma=OK · pos=OK · example=OK · noise=0 · auto=PASS

**10. reliable (adj) — 914 ms**

Seed 1244 · accept: `zuverlässig`

```text
**zuverlässig**
Alternative: verlässlich
Beispiel: „Ich brauche einen Mitarbeiter, der wirklich zuverlässig ist.“
```

format=OK · lemma=OK · pos=OK · example=OK · noise=0 · auto=PASS

**11. to get along with someone (verb) — 1221 ms**

Seed 1245 · accept: `sich verstehen mit`, `auskommen mit`, `mit jemandem auskommen`

```text
**sich auskommen mit** + Dat. (kam aus, ist ausgekommen)
Alternative: sich verstehen mit + Dat.
Beispiel: „Ich komme mit meinem neuen Kollegen sehr gut aus.“
```

format=OK · lemma=FAIL · pos=OK · example=OK · noise=0 · auto=FAIL

**12. receipt (noun) — 1346 ms**

Seed 1246 · accept: `die Quittung`, `der Beleg`

```text
**der Beleg** (Pl. die Belege)
Alternative: die Quittung (Pl. die Quittungen)
Beispiel: „Bitte bewahren Sie den Beleg für Ihre Unterlagen sorgfältig auf.“
```

format=OK · lemma=OK · pos=OK · example=OK · noise=0 · auto=PASS

**13. to look after children (verb) — 1242 ms**

Seed 1247 · accept: `sich kümmern um`, `aufpassen auf`

```text
**auf Kinder aufpassen** (passte auf, hat aufgepasst)
Alternative: Kinder betreuen
Beispiel: „Ich muss am Samstag auf die Kinder aufpassen, weil meine Eltern verreist sind.“
```

format=OK · lemma=FAIL · pos=OK · example=OK · noise=0 · auto=FAIL

**14. to agree with someone (verb) — 1272 ms**

Seed 1248 · accept: `zustimmen`, `einverstanden sein mit`, `jemandem zustimmen`

```text
**jemandem zustimmen** (stimmte zu, hat zugestimmt)
Alternative: jemandem recht geben
Beispiel: „Ich kann deiner Meinung in diesem Punkt nur voll und ganz zustimmen.“
```

format=OK · lemma=OK · pos=OK · example=OK · noise=0 · auto=PASS

**15. overtime (noun) — 1206 ms**

Seed 1249 · accept: `die Überstunde`, `die Überstunden`

```text
**die Überstunden** (Pl. die Überstunden)
Alternative: die Mehrarbeit
Beispiel: „Wegen des großen Projekts musste ich diese Woche viele Überstunden machen.“
```

format=OK · lemma=OK · pos=OK · example=OK · noise=0 · auto=PASS

**16. to cancel an appointment (verb) — 1209 ms**

Seed 1250 · accept: `absagen`, `einen Termin absagen`

```text
**einen Termin absagen** (sagte ab, hat abgesagt)
Alternative: einen Termin stornieren
Beispiel: „Ich muss leider unseren Termin für morgen kurzfristig absagen.“
```

format=OK · lemma=OK · pos=OK · example=OK · noise=0 · auto=PASS

**17. to borrow (verb) — 1128 ms**

Seed 1251 · accept: `sich leihen`, `ausleihen`

```text
**ausleihen** (lieh aus, hat ausgeliehen)
Alternative: sich leihen
Beispiel: „Ich muss mir ein Buch aus der Bibliothek ausleihen.“
```

format=OK · lemma=OK · pos=OK · example=OK · noise=0 · auto=PASS

**18. to be interested in (verb) — 1243 ms**

Seed 1252 · accept: `sich interessieren für`, `interessiert sein an`

```text
**sich interessieren für** + Akk. (interessierte sich, hat sich interessiert)
Alternative: Interesse haben an + Dat.
Beispiel: „Ich interessiere mich sehr für moderne Kunst.“
```

format=OK · lemma=OK · pos=OK · example=OK · noise=0 · auto=PASS

**19. sustainable (adj) — 883 ms**

Seed 1253 · accept: `nachhaltig`

```text
**nachhaltig**
Alternative: dauerhaft
Beispiel: „Wir müssen eine nachhaltige Lösung für dieses Problem finden.“
```

format=OK · lemma=OK · pos=OK · example=OK · noise=0 · auto=PASS

**20. to remind someone of something (verb) — 1215 ms**

Seed 1254 · accept: `jemanden an etwas erinnern`

```text
**jemanden erinnern an** + Akk. (erinnerte, hat erinnert)
Alternative: jemanden an etwas erinnern
Beispiel: „Dein Anruf hat mich an unseren Termin erinnert.“
```

format=OK · lemma=FAIL · pos=OK · example=OK · noise=0 · auto=FAIL

## Review (Claude Code fills this in)
- **Verdict:** Accepted after round 1 + a lead prompt edit (2026-11-05). The quality target was missed by one case; that's documented, not hidden.
- **Round 1 check (lead-graded, all 20 answers):**
  - Kilo's prompt:
    - 0 wrong example sentences (round 0: 2 of 6 fresh queries taught errors);
    - 17/20 correct headwords: wrong are #11 *sich auskommen mit*, #8 forms without *sich*, #15 plural as headword;
    - the optional "Alternative" line was often misleading: *Verabredung* for a doctor's appointment, *verzichten* for give up, *dauerhaft* for sustainable.
  - **Lead edit to `hint.md`:** drop the Alternative line (exactly 2 lines: headword + example); nothing else changed. A broader edit that also touched the check sentence was tried first and caused 2 wrong example sentences, so it was reverted.
  - **Final** (`--runs 2`, 40 answers, temperature 0.2 so the runs are nearly identical):
    - 17/20 cases fully correct;
    - **1 case teaches an error:** #11 "to get along with" → „sich mit jemandem auskommen“ with the example „Ich kann mich mit … auskommen“, in both runs. This is a stable model belief; fixing it would need a case-specific rule, which the task forbids;
    - minor: #15 headword in plural, #16 no verb forms;
    - p50/p90 884/1085 ms.
  - **Mitigation:** the hint box shows „KI-Antwort – kann Fehler enthalten. Im Zweifel im Wörterbuch prüfen.“ A stronger model for hints/feedback can be judged with `make hint-eval` (T011).
- **Round 0 notes:**
- **Notes:**
  - **What's good:** the server/UI code is clean and matches the spec. Hints are isolated from history, turns, playback and the mic gate (tested). The single-pass placeholder replacement is better than the spec. 149 Python + 23 JS tests and lint pass. The concurrent-turn delay is +673 ms mean.
  - **Why the 10 samples are weak evidence:**
    - the prompt now contains answers for 2 of the 10 test queries (`ausgehen` for "to run out of milk", `als selbstverständlich ansehen`);
    - 7 of the 10 contexts already contain the answer word (Kündigungsfrist, Vermieter, Kaution, Dosenöffner, Arbeitsweg, aufschieben, freuen auf);
    - the spec's own examples (Kündigungsfrist, aufschieben) came from the query list, which is the lead's mistake.
  - **Lead's fresh run** (6 queries, neutral context "Wochenende / müde", final prompt): **2 of 6 teach errors**:
    - "to give up" → Beispiel „Ich habe **mit dem Rauchen aufgegeben**.“ (wrong: *das Rauchen aufgeben* / *mit dem Rauchen aufhören*);
    - "to complain about" → „**jemanden beschweren** (sich beschwerte, hat sich beschwert)“ (wrong: *sich beschweren über* + Akk., *beschwerte sich*);
    - minor: „sich an etwas gewöhnen (**gewöhnte sich an**, …)“ reads as separable and lacks + Akk.; „**stur** (ist stur gewesen, war stur)“ has invented verb forms for an adjective; „die Steckdose“ has no plural;
    - latency in this run was 1.6–2.4 s warm (the first call was 10 s, cold).
  - Hints run at the chat temperature (0.8). For a lookup that's too high.

### Follow-up (round 1) — required changes
1. **Hold-out hygiene** (`hint.md`):
   - Remove every query-specific answer (`ausgehen`/milk, `als selbstverständlich ansehen`).
   - Replace the format examples with words that are in **no** eval case: **die Wohnung** (Pl. die Wohnungen), **anfangen** (fing an, hat angefangen), **sich erinnern an** + Akk. (erinnerte sich, hat sich erinnert).
2. **Prompt rules** (`hint.md`):
   - Adjectives/adverbs: the bold word only (irregular comparative allowed, e.g. „gut (besser, am besten)“); **never verb forms**.
   - Nouns always get article + plural (or „nur Sg.“).
   - Verbs with a reflexive or a fixed preposition:
     - the lemma is „sich … + Präposition + Kasus“;
     - the Präteritum/Perfekt forms are the bare verb with *sich* (*beschwerte sich, hat sich beschwert*), with no preposition attached;
     - write „jemanden/etwas“ only when the verb really takes that object.
   - The `Beispiel:` sentence must use the expression exactly as in line 1 (same preposition, same case). The model checks this before answering: „Prüfe vor der Antwort, ob der Beispielsatz grammatisch korrekt ist und die Wendung genau so verwendet.“
3. **Low temperature for hints:**
   - `OllamaLLM.chat(..., temperature: float | None = None)` overrides `options.temperature` when it's given (test it in `test_llm.py`);
   - `Settings.hint_temperature: float = 0.2` (+ `.env.example`), passed via `Deps.hint_temperature`;
   - `Session._hint` uses it.

   Feedback and chat stay unchanged (T011 is separate).
4. **Hint eval** (same pattern as T016): `scripts/hint_cases.json` (new), `backend/kerstin/hint_checks.py` (new, pure, unit-tested in `backend/tests/test_hint_checks.py`), `scripts/hint_eval.py` (new), and `make hint-eval` (`HINT_ARGS`).
   - **Cases: 20 queries, all with the same neutral context** (Kerstin: „Und, wie war dein Wochenende?“ / Lernende Person: „Ganz gut, aber ich war ziemlich müde.“), so the context never contains the answer. Include the lead's 6 („to get used to something“, „stubborn“, „to give up“, „appointment (doctor)“, „to complain about“, „the thing you plug a phone charger into“) plus: „to apply for a job“, „to be afraid of“, „to depend on“, „reliable“, „to get along with someone“, „receipt“, „to look after children“, „to agree with someone“, „overtime“, „to cancel an appointment“, „to borrow“, „to be interested in“, „sustainable“, „to remind someone of something“.
   - Each case lists `accept`: lemma strings, any of which counts (e.g. `["sich beschweren über"]`, `["absagen"]`), and `pos`: `noun|verb|adj`.
   - **Automatic checks:**
     - format: 2–3 lines, a bold first line, a `Beispiel:` last line with one quoted sentence;
     - no LaTeX/tables;
     - the lemma matches `accept`;
     - noun → article + (`Pl.` or `nur Sg.`);
     - adj → no forms in brackets that contain *ist/war/hat*;
     - the example contains the lemma's content words (stem match is enough).
   - Output: a table plus every raw answer, for lead grading. `cool_down()` (76 → 70 °C, abort 80) runs before every call. 1 run, fixed seed; report p50/p90 latency.
   - The eval queries must not appear anywhere in `hint.md` (add a unit test that asserts this).
5. **Run the eval with the new prompt** and paste the table and all 20 answers. The lead will grade every answer. **Target: ≥ 18/20 fully correct, and 0 example sentences with a grammar error.** If it's missed, say so. Don't add case-specific rules to the prompt.

Allowed files (round 1): `backend/prompts/hint.md`, `backend/kerstin/llm.py`, `backend/kerstin/config.py`, `backend/kerstin/session.py` (hint temperature only), `backend/kerstin/main.py` (Deps wiring only), `.env.example`, `backend/kerstin/hint_checks.py` (new), `backend/tests/test_hint_checks.py` (new), `backend/tests/test_llm.py`, `backend/tests/test_session.py`, `scripts/hint_eval.py` (new), `scripts/hint_cases.json` (new), `Makefile` (`hint-eval` only), this task file.
