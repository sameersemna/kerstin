# T006 — Speak the first clause early

**Branch:** `task/T006-early-first-clause` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
Kerstin starts speaking as soon as the **first clause** of her reply is ready (e.g. "Das klingt schön," or "Ich war noch nie in Dresden,"), instead of waiting for the end of the first sentence. Everything after the first chunk stays sentence-based.

## Context
- T002 + T005 (STATUS): after STT, the wait for the first complete sentence is ≈450–550 ms p50 and up to 1.2–1.4 s p90. That's `qwen3:14b` decoding a whole sentence, the biggest cut still available under D011/D012 (medium voice, VAD tail and shared STT unchanged).
- `backend/kerstin/text.py` `SentenceSplitter` emits only at `.!?…` / newline, with a `min_chars` guard. `session.py` creates one splitter per turn.
- Piper adds a short pause at the end of each synthesized chunk. A clause cut at a comma may sound like a slightly longer pause. That's acceptable; Sameer judges the result by ear.

## Spec
1. **Splitter** (`text.py`):
   - Add `first_clause_min_words: int = 0` to `SentenceSplitter.__init__`. 0 means off, which is today's behavior exactly.
   - When it's > 0 and **no chunk has been emitted yet in this splitter**, `feed()` may also emit at a clause boundary. A clause boundary is `,` `;` `:` or ` – ` / ` - ` (dash with spaces) followed by whitespace, when the candidate text before it (stripped) has ≥ `first_clause_min_words` words.
   - Never split at a comma between digits (`3,5`).
   - The emitted chunk keeps its punctuation (`"Das klingt wirklich schön,"`).
   - After the first emission, only sentence boundaries apply, as today.
   - If a sentence end comes before any qualifying clause boundary, emit the sentence as today.
   - The `min_chars` guard still applies to sentences. For the first clause, `first_clause_min_words` replaces it.
2. **Config + wiring:**
   - New setting `tts_first_clause_min_words: int = 4` (`0` disables) in `config.py`.
   - Pass it through `Deps` (e.g. `Deps.first_clause_min_words: int = 4`, set in `main.py`) into the splitter in `Session._turn`.
   - `.env.example`: add a commented line with a one-line explanation.
3. **History / text:**
   - Spoken chunks are still joined with `" "` into history. `"Das klingt schön," + "weil ..."` gives `"Das klingt schön, weil ..."`, which is fine. Nothing else changes.
   - `reply_text` is sent per chunk, as now; `app.js` already appends chunks to one bubble.
   - Metrics: `first_sentence_ms` now means "first chunk (clause or sentence)". Update its description in `docs/PROTOCOL.md`. Don't rename the field.
4. **Tests:**
   - `backend/tests/test_text.py`:
     - (a) default `first_clause_min_words=0`: existing tests unchanged, and a comma doesn't split;
     - (b) with 4: `"Das klingt wirklich schön, weil ich gern Rad fahre. Und du?"` streamed token-by-token gives the first chunk `"Das klingt wirklich schön,"`, then `"weil ich gern Rad fahre."`, then the remainder on flush;
     - (c) a short clause doesn't split early: `"Ja, das stimmt total. Und du?"` → first chunk `"Ja, das stimmt total."`;
     - (d) `"Das kostet 3,5 Euro pro Stück, glaube ich."` never splits inside `3,5`;
     - (e) only the first clause splits early: a second comma in a later sentence doesn't split;
     - (f) dash with spaces works.
   - `backend/tests/test_session.py`: one test with a `FakeLLM` streaming `"Das klingt wirklich schön, weil ich gern Rad fahre."`. Assert two `reply_text` messages for the turn, and that history holds the joined text.
5. **Measure** (port **8771**, medium voice = default now):
   - `make bench` with `BENCH_ARGS="--runs 2"` once with `KERSTIN_TTS_FIRST_CLAUSE_MIN_WORDS=0` and once with `4`.
   - Report p50/p90 for `first_sentence_ms`, `tts_first_ms`, `first_audio_ms` and the VAD-tail estimate for both, plus how many turns actually got an early clause (count turns whose first `reply_text` ends with `,` `;` `:` or a dash).
   - Paste 5 example first chunks.
   - `make smoke` must still pass.

## Hard rules
Same as T005: port 8771 only, leave 8770 alone, no Whisper `/load`, no Ollama config changes, no model pulls, no force-unload, thermal guard.

## Files allowed to change
- `backend/kerstin/text.py`, `backend/kerstin/config.py`, `backend/kerstin/session.py` (splitter construction + `Deps` field only), `backend/kerstin/main.py` (pass the setting into `Deps` only)
- `backend/tests/test_text.py`, `backend/tests/test_session.py`
- `docs/PROTOCOL.md` (`first_sentence_ms` description only)
- `.env.example`
- this task file (Worker report only)

## Out of scope
VAD tail, voice choice, STT, prompts/persona, frontend, the bench script, and streaming TTS within a chunk.

## Acceptance criteria
- [ ] `make test` and `make lint` pass; tests (a)–(f) and the session test exist and pass
- [ ] With `first_clause_min_words=0` the behavior is identical to today (existing tests unchanged)
- [ ] Bench with 4 vs 0: p50 `first_audio_ms` improves (report the delta), and p90 doesn't get worse
- [ ] At least 30 % of bench turns get an early first clause (if fewer, report it and stop; don't touch the prompt)
- [ ] `make smoke` passes
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
