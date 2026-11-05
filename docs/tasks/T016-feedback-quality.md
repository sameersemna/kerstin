# T016 — Feedback quality: eval with planted errors + prompt revision

**Branch:** `task/T016-feedback-quality` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
The end-of-session feedback is the only place Kerstin teaches, so it must be **right**:
- It catches the learner's real errors.
- It never "corrects" correct German.
- It never quotes something the learner didn't say, or something Kerstin said.

We measure this with fixed transcripts that contain known, planted errors. Then we revise `feedback.md` only where the numbers show a problem.

## Context
- `Session.feedback()` builds a transcript (`Lernende Person:` / `Kerstin:` lines), then calls `PromptStore.feedback_prompt(transcript)` → `llm.chat(..., max_tokens=1200)` with the session model (`gemma4:26b`, D015).
- `backend/prompts/feedback.md` asks for:
  - four `###` sections;
  - ≤ 5 errors, each as ❌ original / ✅ correction / 💡 English explanation.
- In T015, 1 of 10 correction explanations was wrong ("auf dem Tisch"). There's no measurement of feedback yet.
- `scripts/persona_eval.py` is the pattern to follow: CLI, `--model`, `--seed`, a thermal `cool_down` between calls, a printed summary, and lead-graded output.
- D008 is resolved: the explanation language is a setting, `en` or `de` (T017, which must be merged first). `PromptStore.feedback_prompt(transcript, lang)` and `Session.feedback(lang)` exist, so this eval covers **both** languages.

## Spec
1. **Fixtures: `scripts/feedback_cases.json`** (new): 5 short conversations, one per scenario key in `backend/prompts/scenarios.json`, each 6–10 messages. Each case has:
   - `scenario`;
   - `messages` (`role` user/assistant, B2-plausible German; Kerstin's lines must be correct German);
   - `planted`: 3–4 learner errors as `{ "utterance_index": i, "wrong": "<exact span in that user line>", "right": "<correct span>", "category": "kasus|verbposition|praeposition|adjektivendung|perfekt-hilfsverb|wortwahl|genus" }`, spread across categories;
   - `correct_tricky`: 2 learner sentences that are **correct** but look suspicious to a weak checker, e.g. "Ich habe mich darüber gefreut.", "Wegen des Wetters …", "Obwohl ich müde war, bin ich gegangen.", "Ich bin den ganzen Tag gelaufen."

   Kerstin's lines contain no errors, so any ❌ quoting Kerstin counts as a failure.
2. **`scripts/feedback_eval.py`** (new) + Makefile target `feedback-eval` (`FEEDBACK_ARGS`):
   - For each case, build the transcript **exactly the way `Session.feedback()` does**. Import or reuse it; don't copy the format by hand. If that needs a tiny pure helper in `session.py` (`format_feedback_transcript(history)`), that's allowed.
   - Run `--runs` (default 1) feedbacks per case **and per language** (`--lang en|de|both`, default `both`), with different seeds (`--seed` base) and a `--model` override, through `OllamaLLM`. Run `cool_down()` (76 → 70 °C, abort 80) before every call.
   - **Automatic checks per feedback** (pure functions in `backend/kerstin/feedback_checks.py`, unit-tested):
     - **structure:** the four headings are present in order, there are ≤ 5 ❌ items, and each ❌ has a ✅ and a 💡 after it;
     - **quote grounding:** every ❌ quote (text inside „…“ / "…" or after ❌) fuzzy-matches a **learner** line (normalized, `SequenceMatcher` ratio ≥ 0.8 against any substring window of that line). Report `ungrounded` and `quotes_kerstin` separately;
     - **planted recall:** a planted error counts as found when some ❌ quote contains its `wrong` span (normalized) **and** the ✅ after it contains `right`;
     - **false corrections:** any ❌ whose quote matches a `correct_tricky` sentence;
     - **no-op corrections:** ❌ and ✅ identical after normalization.
     - **explanation language:** each 💡 line is in the requested language. A simple stop-word heuristic is enough: count hits on `the/is/with/of/to/because/uses` vs `der/die/das/ist/mit/weil/wird`; the majority must match. Report `lang_mismatch`.
   - Output:
     - a summary table per model per model and language (recall %, false corrections, ungrounded, quotes_kerstin, structure failures, lang_mismatch, mean feedback ms);
     - then, for lead grading, every feedback's ❌/✅/💡 triples, grouped by case, each planted error marked found/missed.

     Print to stdout; `--out PATH` writes the same Markdown to a file. The fixtures are synthetic, so writing to a file is fine; don't write anywhere by default.
3. **Baseline run:** `gemma4:26b`, `--lang both --runs 1`, all 5 cases (10 feedbacks), pasted into the report.
4. **Prompt revision** (`backend/prompts/feedback.md`), **only if the baseline shows** recall < 80 %, any false or no-op correction, any ungrounded or Kerstin quote, or structure failures or language mismatches, in either language. Allowed levers:
   - require exact quotes from „Lernende Person“ lines only;
   - "only flag errors you are certain about; when unsure, leave it out";
   - "don't flag correct alternatives as errors";
   - order errors by importance;
   - keep the explanation to one English sentence naming the rule.

   Keep the four-section structure, the markers (T004 renders them) and the `{explanation_language}` placeholder (T017). Re-run the same eval after the change (same seeds) and paste **before/after** numbers plus one full before/after feedback for the same case (CLAUDE.md persona/prompt rule).
5. **Tests:** `backend/tests/test_feedback_checks.py` covers every check with handcrafted Markdown:
   - well-formed;
   - missing section;
   - 6 errors;
   - ❌ without 💡;
   - a quote from Kerstin;
   - an ungrounded quote;
   - planted error found / found-but-wrong-correction / missed;
   - English and German 💡 lines, plus a mismatch;
   - false correction;
   - no-op.

## Files allowed to change
- `scripts/feedback_eval.py` (new), `scripts/feedback_cases.json` (new), `Makefile` (`feedback-eval` target only)
- `backend/kerstin/feedback_checks.py` (new), `backend/tests/test_feedback_checks.py` (new)
- `backend/kerstin/session.py` (only to extract a pure `format_feedback_transcript` helper; no behaviour change)
- `backend/prompts/feedback.md` (only per spec 4)
- this task file (Worker report only)

## Out of scope
- A separate feedback model (T011).
- Changing `max_tokens`.
- Frontend rendering (T004).
- Storing feedback (T020).
- Adding feedback languages or changing the language setting (T017).
- Changing the persona prompt.

## Acceptance criteria
- [ ] `make test` and `make lint` pass; the feedback-check tests listed above exist
- [ ] `make feedback-eval` runs end-to-end on `gemma4:26b` with the thermal cool-down. The baseline table and all triples are pasted in the report.
- [ ] If the prompt changed: before/after numbers on the same seeds, plus one full before/after feedback. Target: recall ≥ 80 %, 0 false corrections, 0 Kerstin quotes, 0 structure failures. If a target is missed, say so; don't tune the fixtures to pass.
- [ ] The fixtures' "correct" lines are really correct German (the lead will check them all)
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
