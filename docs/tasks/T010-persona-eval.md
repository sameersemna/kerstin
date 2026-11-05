# T010 — Persona evaluation harness + first prompt tuning

**Branch:** `task/T010-persona-eval` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
1. One command (`make persona-eval`) runs scripted text-only conversations in all 5 scenarios through the real `Session` code path and prints full transcripts plus automatic persona checks. The lead can then judge German correctness and tone, and compare prompt versions fairly.
2. A first, evidence-based revision of `backend/prompts/persona.md` that reduces the measured violations without making replies worse. The before/after transcripts are the required persona-change samples (CLAUDE.md).

## Context
- Persona contract (CLAUDE.md, D002): correct B2-range German; a peer, not a teacher; never corrects mid-conversation; 1–3 sentences; no English/markdown/emoji.
- Problems seen with `qwen3:14b` (T001/T002 reviews):
  - grammar slips: "haben sie auch geregnet", "Hast du irgendeine Hobbys", "Ich habe dort noch nie gewesen", "den Frauenkirche", "es klingt wie ein schöner Tag trotzdem";
  - replies of 4+ sentences;
  - odd facts ("Hafenamt", "Hamburger Ufer");
  - it repeats an earlier answer when the learner repeats a sentence verbatim.
- The model stays `qwen3:14b` (D009). **D007 (learner flavour) and D008 (feedback language) are Open: don't change those aspects.**
- Fixed `KERSTIN_LLM_SEED` gives identical first replies; histories may drift later (T006 review). Compare prompt versions with the **same seeds and the same learner lines**.

## Spec
1. **Reply checks** (`backend/kerstin/reply_checks.py`, new; pure functions, no I/O). `check_reply(text: str) -> list[str]` returns violation codes:
   - `too_long`: more than 3 sentences. Reuse `SentenceSplitter` logic, or a simple count of `.!?` boundaries that respects the abbreviation list in `text.py`.
   - `no_question`: no `?`. This is informational only; peers don't always ask.
   - `markdown_or_emoji`: `*`, `#`, `- ` at line start, backticks, or an emoji (Unicode `So` category / ranges).
   - `digits`: any digit 0–9 (the persona asks for numbers spelled out).
   - `english`: ≥ 2 tokens from a small built-in list of common English words (`the, and, you, is, are, what, really, okay, cool, nice`). Keep the list short and documented; `okay`/`cool` alone don't count.
   - `correction`: German correction phrases such as `man sagt`, `richtig heißt`, `richtig wäre`, `du meinst wohl`, `kleiner Tipp`, `korrekt ist`, `es heißt nicht` (case-insensitive).
   - Tests: `backend/tests/test_reply_checks.py`, with one positive and one negative case per code.
2. **Eval script** (`scripts/persona_eval.py`) + `make persona-eval` (`$(PY) scripts/persona_eval.py $(EVAL_ARGS)`):
   - Text-only, using the **real `Session`** with the real `OllamaLLM` and `PromptStore`, a fake STT that returns the scripted learner line, `NoTTS`, and a dummy PCM ≥ 0.5 s. This exercises history, splitter and warm-up exactly as in production.
   - Built-in script: for each of the 5 scenarios, **6 learner lines** at realistic B2 level, including:
     - at least 2 lines with typical learner errors (e.g. wrong article, verb position, "ich habe gegangen"), to test that Kerstin does **not** correct;
     - 1 line in English ("Sorry, how do you say 'deadline' in German?");
     - 1 line repeating an earlier line verbatim;
     - 1 line asking explicitly for a correction ("Kannst du mich bitte korrigieren? Ich habe gesagt: …"). Here a correction is allowed, so mark this line as `correction_allowed`.
   - CLI: `--seed` (default 1234; sets `KERSTIN_LLM_SEED` for the in-process settings), `--scenario` (default all), `--persona PATH` (default `backend/prompts/persona.md`; lets you evaluate a candidate prompt without overwriting the file).
   - Output to stdout only:
     - (a) the full transcript per scenario (learner → Kerstin), with each reply's violation codes inline;
     - (b) a summary table: violations per code, total replies, mean sentences per reply, mean words per reply;
     - (c) a list of every reply flagged `correction` where it wasn't allowed.
   - Thermal guard as in the smoke test. 5 × 6 = 30 LLM turns per run is the limit; don't add loops.
3. **Baseline:** run `make persona-eval` with the current prompt and paste the full output into the report.
4. **Prompt revision** (`backend/prompts/persona.md`), German, minimal and targeted. Keep all existing rules and the `{scenario}` placeholder, and don't touch D007/D008 topics. Allowed directions:
   - sharpen the length rule ("höchstens drei Sätze");
   - "Formuliere lieber einfach und sicher als kompliziert, wenn du dir bei Artikel oder Kasus nicht sicher bist";
   - "Erfinde keine Orte oder Fakten; bleib bei allgemein bekannten Dingen";
   - "Wenn dein Gegenüber etwas wiederholt, reagiere darauf, statt deine letzte Antwort zu wiederholen";
   - one short few-shot example exchange (2 turns max) showing the tone and length.

   Keep the prompt within +25 % of its current length (a longer system prompt costs prompt-eval time). Evaluate candidates with `--persona` on a copy, then write the winner to `persona.md`.
5. **After:** run the eval again with the same seed. Paste the full output, plus a before/after summary table and **3 before/after sample exchanges** (the same learner line, both replies).
6. **Latency check:** run `make bench BENCH_ARGS="--runs 1"` with a fixed seed before and after the prompt change, as a paired comparison. Report the p50 `llm_first_token_ms` and `first_audio_ms`; the prompt change must not cost more than ~50 ms p50.

## Hard rules
Same as T006: port 8771 for any server, leave 8770 alone, no Whisper `/load`, no Ollama config changes, no model pulls, no force-unload, thermal guard. Don't commit any eval output to the repo except in this task file's report.

## Files allowed to change
- `backend/kerstin/reply_checks.py` (new), `backend/tests/test_reply_checks.py` (new)
- `scripts/persona_eval.py` (new)
- `backend/prompts/persona.md`
- `Makefile` (`persona-eval` target)
- this task file (Worker report only)

## Out of scope
Scenario texts/openers, feedback prompt, model choice, runtime enforcement of the checks (e.g. truncating long replies; a possible later task), frontend, and D007/D008 topics.

## Acceptance criteria
- [ ] `make test` and `make lint` pass; `test_reply_checks.py` covers every code
- [ ] `make persona-eval` runs 30 turns with 0 errors and prints (a)–(c)
- [ ] After vs before (same seed): `too_long` and `digits` counts don't increase, and `correction` (where not allowed) is 0 after
- [ ] Report contains the full before/after transcripts and 3 before/after sample exchanges
- [ ] `persona.md` grows ≤ 25 %; paired bench: p50 `llm_first_token_ms` within +50 ms
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
