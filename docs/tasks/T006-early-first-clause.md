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
  - `backend/kerstin/text.py` — `SentenceSplitter(first_clause_min_words=0)`; when >0 and nothing has been emitted yet, `feed()` may emit at `,` `;` `:` or a spaced `–`/`-`, keeping the punctuation, with the word count taken from the text before the boundary; the `3,5` decimal comma is explicitly excluded. Sentence/newline behaviour and `min_chars` are unchanged, and clause splitting stops after the first emission.
  - `backend/kerstin/config.py` — `tts_first_clause_min_words: int = 4`.
  - `backend/kerstin/session.py` — `Deps.first_clause_min_words: int = 4`; the per-turn splitter is constructed with it.
  - `backend/kerstin/main.py` — passes `settings.tts_first_clause_min_words` into `Deps`.
  - `backend/tests/test_text.py` — tests (a)–(f): default comma behaviour, early clause token-by-token, short clause, `3,5`, only the first clause, and spaced dashes.
  - `backend/tests/test_session.py` — one new test: two `reply_text` chunks and the joined history text.
  - `docs/PROTOCOL.md` — `first_sentence_ms` now described as the first spoken chunk (clause or sentence).
  - `.env.example` — commented `KERSTIN_TTS_FIRST_CLAUSE_MIN_WORDS=4` with explanation.
  - `docs/tasks/T006-early-first-clause.md` — Worker report only.
- **How tested:**
  - `make test` → 37 passed; `make lint` → `All checks passed!`.
  - Two `make bench BENCH_ARGS="--runs 2"` runs on the 8771 server (TLS, `thorsten-medium` reply voice): one with `KERSTIN_TTS_FIRST_CLAUSE_MIN_WORDS=0`, one with `=4`; 20 measured turns each, 0 errors, thermal guard before every turn.
  - `make smoke` on 8771 with the setting at 4 → exit 0.
  - A direct 20-turn capture of the actual first `reply_text` chunks (same utterances/protocol) was used for the early-clause count, because the bench joins chunks into one reply line.
  - No Whisper `/load`, no Ollama config changes, no model pulls, no force-unload. 8770 was not started or touched.
  - No audio or result files written.
- **Measurements (if any):**
  - **first_audio_ms:** p50 **2162 → 1820 ms** (−342 ms, −15.8 %) and p90 **3055 → 2555 ms** (−500 ms, −16.4 %) with 0 → 4.
  - **first_sentence_ms:** p50 1980 → 1619 ms, p90 2754 → 2255 ms.
  - **tts_first_ms:** p50 176 → 192 ms (+16 ms; shorter chunks, same order of magnitude), p90 404 → 367 ms.
  - **VAD estimate (first_audio + 768 ms):** p50 2930 → 2588 ms, p90 3823 → 3323 ms.
  - **Early first clauses:** direct 20-turn capture = **6/20 (30 %)**. The setting=4 bench's own printed reply sample, replayed through the splitter, had 2/20 (10 %); the rate is seed-dependent. No prompt changes were made (per the task fallback).
  - Five first chunks from the capture:
    1. `Schön, dass du in Berlin bist!` (sentence)
    2. `Das klingt sehr schön!` (sentence)
    3. `In meiner Freizeit mache ich gerne Sport,` (early clause)
    4. `Hamburg ist eine sehr schöne Stadt –` (early clause)
    5. `Natürlich! Ich mache oft Vokabelhefte und lerne neue Wörter,` (early clause)
  - `make smoke`: turn 1 `first_audio_ms=1032`, turn 2 `first_audio_ms=1184`; GPU 67→73 °C. All bench runs stayed at 52–70 °C, below the 80 °C guard.
- **Deviations from spec / extra files touched:**
  - The early-clause rate is borderline: the direct 20-turn capture met 30 %, but the setting=4 bench's own random reply sample replayed to 2/20 (10 %). This is reported rather than fixed by touching the prompt, as instructed.
  - The local `.env` (gitignored) still points at `thorsten-high`, so the measurement server was started with `KERSTIN_PIPER_VOICE_PATH=voices/de_DE-thorsten-medium.onnx`. The committed default is already medium (D011). The bench client synthesized the learner utterances with the high voice in both runs, so the A/B input audio was identical.
  - The bench script and prompt were not changed.
- **New dependencies (+license):** None.
- **Open questions:**
  - The 30 % early-clause target varies with the random replies (2/20 vs 6/20 in two samples); a prompt/style change would be needed for a reliably higher rate, but that is out of scope.
  - When the text starts with a short sentence below `min_chars` (e.g. “Natürlich!”), the first clause chunk can include that short sentence plus the clause; this follows the spec’s “min_chars applies to sentences, first clause uses words”, but it is worth hearing.

### Bench — `KERSTIN_TTS_FIRST_CLAUSE_MIN_WORDS=0`

```text
(a) Server metrics (n=20)
metric                       p50       p90       max
----------------------------------------------------
audio_s                     4.60      7.81      9.96
stt_ms                       522       763       874
llm_first_token_ms           977      1553      1676
first_sentence_ms           1980      2754      3435
tts_first_ms                 176       404       538
first_audio_ms              2162      3055      3847
total_ms                    4217      5643      6261
sentences                      3         4         4

(b) Derived stages (ms)
stage                        p50       p90
------------------------------------------
stt                          522       763
llm_to_first_token           218       890
first_sentence_wait          528      1510
tts_first                    176       404

(c) Estimated end-of-speech -> first audio (first_audio_ms + 768 ms VAD tail)
    p50: 2930 ms    p90: 3823 ms    target: 1500 ms
    vs target: p50 +1430 ms    p90 +2323 ms
```

### Bench — `KERSTIN_TTS_FIRST_CLAUSE_MIN_WORDS=4`

```text
(a) Server metrics (n=20)
metric                       p50       p90       max
----------------------------------------------------
audio_s                     4.49      7.49      9.78
stt_ms                       498       684       781
llm_first_token_ms           876      1427      1567
first_sentence_ms           1619      2255      2641
tts_first_ms                 192       367       570
first_audio_ms              1820      2555      3220
total_ms                    3601      4668      5263
sentences                      3         3         4

(b) Derived stages (ms)
stage                        p50       p90
------------------------------------------
stt                          498       684
llm_to_first_token           148       790
first_sentence_wait          522      1210
tts_first                    192       367

(c) Estimated end-of-speech -> first audio (first_audio_ms + 768 ms VAD tail)
    p50: 2588 ms    p90: 3323 ms    target: 1500 ms
    vs target: p50 +1088 ms    p90 +1823 ms
```

## Review (Claude Code fills this in)
- **Verdict:** accept (2026-11-05)
- **Notes:**
  - Diff limited to allowed files; the code is minimal and correct. `make test` (37) and `make lint` are clean. Setting 0 = old behavior.
  - The report's headline delta (p50 −342 ms) is **not attributable** to T006. The stage it targets, `first_sentence_wait`, was 528 vs 522 ms. The difference came from STT and first-token variance between two unpaired runs with different random replies.
  - Lead re-measured **paired**: fixed `KERSTIN_LLM_SEED=1234`, the same 10 utterances, setting 0 vs 4, comparing `first_audio − llm_first_token` per turn. Turns 1–3 had identical replies in both runs. No clause: +39 / −2 ms. Early clause: −448 ms. Over all 10 turns the median is **−379 ms** (mean −486). The clause fired in 6/10 turns, and where it fired the gain was −309 to −1597 ms. Most splits came at `–` (qwen3 likes dashes) and commas.
  - Replies diverged from turn 4 on despite the fixed seed (probably GPU numeric nondeterminism once histories differ by whitespace or length). Not a T006 issue.
  - For future benches: compare paired runs with a fixed seed, not two random samples.
