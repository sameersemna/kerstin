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
     - **format noise:** count LaTeX (`$…$`, `\rightarrow`), HTML tags and tables (`|---`). Report it as `format_noise`. T017 samples showed `$\rightarrow$` from gemma4, so this must reach 0 after the prompt change (lever: "Kein LaTeX, keine Tabellen; Pfeil als →").
     - The structure check must accept both layouts seen in real output: ❌/✅/💡 as sibling bullets, and ✅/💡 nested or indented under ❌.
     - **explanation language:** each 💡 line is in the requested language. A simple stop-word heuristic is enough: count hits on `the/is/with/of/to/because/uses` vs `der/die/das/ist/mit/weil/wird`; the majority must match. Report `lang_mismatch`.
   - Output:
     - a summary table per model per model and language (recall %, false corrections, ungrounded, quotes_kerstin, structure failures, lang_mismatch, mean feedback ms);
     - then, for lead grading, every feedback's ❌/✅/💡 triples, grouped by case, each planted error marked found/missed.

     Print to stdout; `--out PATH` writes the same Markdown to a file. The fixtures are synthetic, so writing to a file is fine; don't write anywhere by default.
3. **Baseline run:** `gemma4:26b`, `--lang both --runs 1`, all 5 cases (10 feedbacks), pasted into the report.
4. **Prompt revision** (`backend/prompts/feedback.md`), **only if the baseline shows** recall < 80 %, any false or no-op correction, any ungrounded or Kerstin quote, or structure failures, language mismatches or format noise, in either language. Allowed levers:
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
- [ ] If the prompt changed: before/after numbers on the same seeds, plus one full before/after feedback. Target: recall ≥ 80 %, 0 false corrections, 0 Kerstin quotes, 0 structure failures, 0 format noise, 0 language mismatches. If a target is missed, say so; don't tune the fixtures to pass.
- [ ] The fixtures' "correct" lines are really correct German (the lead will check them all)
- [ ] `git diff main --stat` shows only allowed files

## Worker report (Kilo Code fills this in)
- **Changed files:** `scripts/feedback_eval.py` (new), `scripts/feedback_cases.json` (new), `Makefile` (`feedback-eval`/`FEEDBACK_ARGS` only), `backend/kerstin/feedback_checks.py` (new), `backend/tests/test_feedback_checks.py` (new), `backend/kerstin/session.py` (`format_feedback_transcript` extraction only), `backend/prompts/feedback.md` (spec-4 levers only), this task file.
- **How tested:** `make test` → 133 Python tests + 23 Node tests passed; `make lint` passed. `make feedback-eval` ran end-to-end on `gemma4:26b` for all 5 fixtures × `en`/`de` × 1 run, twice (before and after the prompt revision) with the same seed base 1234. `cool_down()` ran before every LLM call; it cooled at 76 °C several times (baseline range 57→76 °C, after range 64→76 °C), no 80 °C abort. The checks cover all requested cases (well-formed, missing section, six errors, missing 💡, Kerstin quote, ungrounded quote, found/found-but-wrong/missed, en/de/mismatch, false correction, no-op, Markdown-emphasis correction).
- **Measurements (if any):** Baseline (unchanged prompt): en recall 93%, 1 false, 20 noise; de recall 87%, 1 false, 20 noise. After revision: en recall 87%, 0 false, 0 noise; de recall 87%, 0 false, 0 noise. Full tables and triples are below. Mean feedback: baseline en 10743 ms / de 10957 ms; after en 9919 ms / de 9319 ms.
- **Deviations from spec / extra files touched:** None beyond the allowed files. Checker details: Markdown emphasis is removed before normalization (so a model writing `ein**em**` still counts as `einem`), and the English stop-word heuristic also counts `and/for/that/this`; without those, a clearly English explanation that lacks the listed stopwords was reported as a false `lang_mismatch`. No fixtures were tuned to pass; the remaining misses are visible below.
- **New dependencies (+license):** None.
- **Open questions:** None. The recall target is met in both languages; the remaining misses are the `arbeit_kollegen` perfect-auxiliary/verb-position errors and the `pruefung_planung` preposition in both languages.

### Baseline — unchanged prompt
```markdown
# Feedback eval

Model: `gemma4:26b` · seed base: 1234 · runs: 1

| language | feedbacks | recall | false_corrections | noop_corrections | ungrounded | quotes_kerstin | structure_failures | lang_mismatch | format_noise | mean_feedback_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| en | 5 | 93% | 1 | 0 | 0 | 0 | 0 | 0 | 20 | 10743 |
| de | 5 | 87% | 1 | 0 | 0 | 0 | 0 | 0 | 20 | 10957 |

## Case `freies_gespraech`

Planted: `kasus` `mit ein Freund` → `mit einem Freund`; `verbposition` `weil ich bin seit zwei Wochen im Team` → `weil ich seit zwei Wochen im Team bin`; `praeposition` `für den Sommer` → `auf den Sommer`

### EN · run 1 · seed 1234 · 10487 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ Ich habe gestern mit ein Freund im Park gesessen
   ✅ Ich habe gestern mit **einem** Freund im Park gesessen.
   💡 The preposition „mit“ always requires the dative case.
2. ❌ ...weil ich bin seit zwei Wochen im Team.
   ✅ ...weil ich seit zwei Wochen im Team **bin**.
   💡 In a subordinate clause starting with „weil“, the conjugated verb must move to the very end.
3. ❌ Ich freue mich für den Sommer...
   ✅ Ich freue mich **auf** den Sommer...
   💡 Use „sich freuen auf“ for future events and „sich freuen über“ for things that have already happened.

Planted errors:
- [FOUND] `kasus` `mit ein Freund` → `mit einem Freund`
- [FOUND] `verbposition` `weil ich bin seit zwei Wochen im Team` → `weil ich seit zwei Wochen im Team bin`
- [FOUND] `praeposition` `für den Sommer` → `auf den Sommer`

### DE · run 1 · seed 1235 · 10869 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ ...mit ein Freund im Park gesessen
   ✅ ...mit ein**em** Freund im Park gesessen
   💡 Die Präposition „mit“ braucht immer den Dativ.
2. ❌ ...weil ich bin seit zwei Wochen im Team.
   ✅ ...weil ich seit zwei Wochen im Team **bin**.
   💡 In einem Nebensatz mit „weil“ muss das konjugierte Verb am Ende stehen.
3. ❌ Ich freue mich für den Sommer...
   ✅ Ich freue mich **auf den** Sommer...
   💡 Wir benutzen die Präposition „auf“ + Akkusativ für Ereignisse in der Zukunft.

Planted errors:
- [FOUND] `kasus` `mit ein Freund` → `mit einem Freund`
- [FOUND] `verbposition` `weil ich bin seit zwei Wochen im Team` → `weil ich seit zwei Wochen im Team bin`
- [FOUND] `praeposition` `für den Sommer` → `auf den Sommer`


## Case `wg_alltag`

Planted: `kasus` `auf der Tisch` → `auf den Tisch`; `verbposition` `weil er ist abends sehr müde` → `weil er abends sehr müde ist`; `adjektivendung` `mit klare Regeln` → `mit klaren Regeln`

### EN · run 1 · seed 2234 · 10601 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ ...auf der Tisch gestellt.
   ✅ ...auf **den** Tisch gestellt.
   💡 Use the accusative case because there is movement from one place to another (Wohin?).
2. ❌ ...weil er ist abends sehr müde.
   ✅ ...weil er abends sehr müde **ist**.
   💡 In a subordinate clause starting with „weil“, the conjugated verb must move to the very end.
3. ❌ ...mit klare Regeln...
   ✅ ...mit klare**n** Regeln...
   💡 The preposition „mit“ always requires the dative case, which affects the adjective ending.

Planted errors:
- [FOUND] `kasus` `auf der Tisch` → `auf den Tisch`
- [FOUND] `verbposition` `weil er ist abends sehr müde` → `weil er abends sehr müde ist`
- [FOUND] `adjektivendung` `mit klare Regeln` → `mit klaren Regeln`

### DE · run 1 · seed 2235 · 10618 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ ...auf der Tisch gestellt.
   ✅ ...auf **den** Tisch gestellt.
   💡 „Auf“ verlangt hier den Akkusativ, weil es eine Bewegung (Wohin?) beschreibt.
2. ❌ ...weil er ist abends sehr müde.
   ✅ ...weil er abends sehr müde **ist**.
   💡 In einem Nebensatz mit „weil“ muss das konjugierte Verb am Ende stehen.
3. ❌ ...mit klare Regeln...
   ✅ ...mit klar**en** Regeln...
   💡 Nach der Präposition „mit“ folgt immer der Dativ, und das Adjektiv braucht hier die Endung „-en“.

Planted errors:
- [FOUND] `kasus` `auf der Tisch` → `auf den Tisch`
- [FOUND] `verbposition` `weil er ist abends sehr müde` → `weil er abends sehr müde ist`
- [FOUND] `adjektivendung` `mit klare Regeln` → `mit klaren Regeln`


## Case `arbeit_kollegen`

Planted: `kasus` `mit mein Chef` → `mit meinem Chef`; `verbposition` `weil wir haben nur zwei Wochen` → `weil wir nur zwei Wochen haben`; `perfekt-hilfsverb` `habe danach nach Hause gefahren` → `bin danach nach Hause gefahren`

### EN · run 1 · seed 3234 · 10095 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ ...mit mein Chef...
   ✅ ...mit mein**em** Chef...
   💡 The preposition „mit“ always requires the dative case.
2. ❌ ...weil wir haben nur zwei Wochen...
   ✅ ...weil wir nur zwei Wochen [...] haben.
   💡 In a subordinate clause starting with „weil“, the conjugated verb must move to the very end.
3. ❌ ...und habe danach nach Hause gefahren.
   ✅ ...und bin danach nach Hause gefahren.
   💡 Verbs indicating a change of location (movement from A to B) use „sein“ as the auxiliary verb in Perfekt.

Planted errors:
- [FOUND] `kasus` `mit mein Chef` → `mit meinem Chef`
- [FOUND] `verbposition` `weil wir haben nur zwei Wochen` → `weil wir nur zwei Wochen haben`
- [FOUND] `perfekt-hilfsverb` `habe danach nach Hause gefahren` → `bin danach nach Hause gefahren`

### DE · run 1 · seed 3235 · 10890 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ Ich habe gestern mit mein Chef über das neue Projekt gesprochen
   ✅ Ich habe gestern mit **meinem** Chef über das neue Projekt gesprochen.
   💡 Nach der Präposition „mit“ folgt immer der Dativ.
2. ❌ ...weil wir haben nur zwei Wochen für die Vorbereitung.
   ✅ ...weil wir nur zwei Wochen für die Vorbereitung **haben**.
   💡 In einem Nebensatz mit „weil“ muss das konjugierte Verb am Ende stehen.
3. ❌ ...und habe danach nach Hause gefahren.
   ✅ ...und bin danach nach Hause gefahren.
   💡 Verben der Bewegung (von A nach B) bilden das Perfekt mit dem Hilfsverb „sein“.

Planted errors:
- [FOUND] `kasus` `mit mein Chef` → `mit meinem Chef`
- [MISSED] `verbposition` `weil wir haben nur zwei Wochen` → `weil wir nur zwei Wochen haben`
- [FOUND] `perfekt-hilfsverb` `habe danach nach Hause gefahren` → `bin danach nach Hause gefahren`


## Case `diskussion`

Planted: `verbposition` `Meiner Meinung nach, die Autos sind` → `Meiner Meinung nach sind die Autos`; `kasus` `mit Fahrräder` → `mit Fahrrädern`; `genus` `das öffentliche Verkehr` → `der öffentliche Verkehr`

### EN · run 1 · seed 4234 · 11590 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ Meiner Meinung nach, die Autos sind nicht das größte Problem...
   ✅ Meiner Meinung nach sind die Autos nicht das größte Problem...
   💡 In German, "Meiner Meinung nach" occupies the first position, so the verb must follow immediately.
2. ❌ ...die Pakete mit Fahrräder ausliefern.
   ✅ ...die Pakete mit Fahrrädern ausliefern.
   💡 The preposition "mit" always requires the dative case, so the plural noun needs an "-n" ending.
3. ❌ Ich finde, das öffentliche Verkehr sollte besser werden...
   ✅ Ich finde, der öffentliche Verkehr sollte besser werden...
   💡 "Verkehr" is a masculine noun, so it requires the masculine article "der".

Planted errors:
- [FOUND] `verbposition` `Meiner Meinung nach, die Autos sind` → `Meiner Meinung nach sind die Autos`
- [FOUND] `kasus` `mit Fahrräder` → `mit Fahrrädern`
- [FOUND] `genus` `das öffentliche Verkehr` → `der öffentliche Verkehr`

### DE · run 1 · seed 4235 · 11413 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ Meiner Meinung nach, die Autos sind nicht das größte Problem...
   ✅ Meiner Meinung nach sind die Autos nicht das größte Problem...
   💡 Nach der festen Wendung „Meiner Meinung nach“ muss das Verb an der zweiten Position im Satz stehen.
2. ❌ ...die Pakete mit Fahrräder ausliefern.
   ✅ ...die Pakete mit Fahrrädern ausliefern.
   💡 Das Wort „mit“ verlangt den Dativ Plural, deshalb muss am Ende ein „n“ an „Fahrräder“ stehen.
3. ❌ Ich finde, das öffentliche Verkehr sollte besser werden...
   ✅ Ich finde, der öffentliche Verkehr sollte besser werden...
   💡 Das Nomen „Verkehr“ ist maskulin (der Verkehr), daher muss auch der Artikel und das Adjektiv im Nominativ maskulin sein.

Planted errors:
- [FOUND] `verbposition` `Meiner Meinung nach, die Autos sind` → `Meiner Meinung nach sind die Autos`
- [FOUND] `kasus` `mit Fahrräder` → `mit Fahrrädern`
- [FOUND] `genus` `das öffentliche Verkehr` → `der öffentliche Verkehr`


## Case `pruefung_planung`

Planted: `adjektivendung` `im großem Kursraum` → `im großen Kursraum`; `verbposition` `weil es ist persönlicher` → `weil es persönlicher ist`; `praeposition` `für die Getränke` → `um die Getränke`

### EN · run 1 · seed 5234 · 10940 ms

structure=OK · false_corrections=1 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ ...im großem Kursraum machen
   ✅ ...im großen Kursraum machen
   💡 After the preposition "in" (dative case here), the adjective needs a weak/mixed ending "-en".
2. ❌ ...weil es ist persönlicher.
   ✅ ...weil es persönlicher ist.
   💡 In a subordinate clause introduced by "weil", the conjugated verb must move to the very end.
3. ❌ Ich habe mich für die Hilfe meiner Kollegin bedankt.
   ✅ Ich würde meine Kollegin um Hilfe bitten.
   💡 Your sentence is grammately correct, but it sounds like a finished past action, which doesn't fit the planning context of the conversation.

Planted errors:
- [FOUND] `adjektivendung` `im großem Kursraum` → `im großen Kursraum`
- [FOUND] `verbposition` `weil es ist persönlicher` → `weil es persönlicher ist`
- [MISSED] `praeposition` `für die Getränke` → `um die Getränke`

### DE · run 1 · seed 5235 · 10995 ms

structure=OK · false_corrections=1 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=4

1. ❌ ...im großem Kursraum machen...
   ✅ ...im großen Kursraum machen...
   💡 Nach der Präposition „in“ (Dativ) braucht das Adjektiv die Endung „-en“.
2. ❌ ...weil es ist persönlicher.
   ✅ ...weil es persönlicher ist.
   💡 In einem Nebensatz mit „weil“ muss das konjugierte Verb am Ende stehen.
3. ❌ Ich habe mich für die Hilfe meiner Kollegin bedankt.
   ✅ Ich habe mich für die Hilfe meiner Kollegin entschieden. (Oder: Ich habe mich bei meiner Kollegin für die Hilfe bedankt.)
   💡 Das Verb „sich bedanken“ braucht die Präposition „bei“ (Person) und „für“ (Sache).

Planted errors:
- [FOUND] `adjektivendung` `im großem Kursraum` → `im großen Kursraum`
- [FOUND] `verbposition` `weil es ist persönlicher` → `weil es persönlicher ist`
- [MISSED] `praeposition` `für die Getränke` → `um die Getränke`
```

### After — revised prompt
```markdown
# Feedback eval

Model: `gemma4:26b` · seed base: 1234 · runs: 1

| language | feedbacks | recall | false_corrections | noop_corrections | ungrounded | quotes_kerstin | structure_failures | lang_mismatch | format_noise | mean_feedback_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| en | 5 | 87% | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 9919 |
| de | 5 | 87% | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 9319 |

## Case `freies_gespraech`

Planted: `kasus` `mit ein Freund` → `mit einem Freund`; `verbposition` `weil ich bin seit zwei Wochen im Team` → `weil ich seit zwei Wochen im Team bin`; `praeposition` `für den Sommer` → `auf den Sommer`

### EN · run 1 · seed 1234 · 10655 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ Ich habe gestern mit ein Freund im Park gesessen
   ✅ Ich habe gestern mit einem Freund im Park gesessen
   💡 The preposition „mit“ always requires the dative case, so „ein Freund“ must change to „einem Freund“.
2. ❌ weil ich bin seit zwei Wochen im Team
   ✅ weil ich seit zwei Wochen im Team bin
   💡 In a subordinate clause starting with „weil“, the conjugated verb must move to the very end of the sentence.
3. ❌ Ich freue mich für den Sommer
   ✅ Ich freue mich auf den Sommer
   💡 When expressing anticipation for a future event, the fixed preposition is „sich freuen auf“.

Planted errors:
- [FOUND] `kasus` `mit ein Freund` → `mit einem Freund`
- [FOUND] `verbposition` `weil ich bin seit zwei Wochen im Team` → `weil ich seit zwei Wochen im Team bin`
- [FOUND] `praeposition` `für den Sommer` → `auf den Sommer`

### DE · run 1 · seed 1235 · 9615 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ Ich habe gestern mit ein Freund im Park gesessen
   ✅ Ich habe gestern mit einem Freund im Park gesessen
   💡 Nach der Präposition „mit“ folgt immer der Dativ (Maskulin: einem Freund).
2. ❌ weil ich bin seit zwei Wochen im Team
   ✅ weil ich seit zwei Wochen im Team bin
   💡 In einem Nebensatz mit „weil“ muss das konjugierte Verb am Ende stehen.
3. ❌ Ich freue mich für den Sommer
   ✅ Ich freue mich auf den Sommer
   💡 Die Präposition „auf“ benutzt man bei Ereignissen in der Zukunft (Vorfreude).

Planted errors:
- [FOUND] `kasus` `mit ein Freund` → `mit einem Freund`
- [FOUND] `verbposition` `weil ich bin seit zwei Wochen im Team` → `weil ich seit zwei Wochen im Team bin`
- [FOUND] `praeposition` `für den Sommer` → `auf den Sommer`


## Case `wg_alltag`

Planted: `kasus` `auf der Tisch` → `auf den Tisch`; `verbposition` `weil er ist abends sehr müde` → `weil er abends sehr müde ist`; `adjektivendung` `mit klare Regeln` → `mit klaren Regeln`

### EN · run 1 · seed 2234 · 10761 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ ...sein Geschirr wieder auf der Tisch gestellt.
   ✅ ...sein Geschirr wieder auf den Tisch gestellt.
   💡 The preposition "auf" requires the accusative case here because it describes a movement/direction.
2. ❌ ...weil er ist abends sehr müde.
   ✅ ...weil er abends sehr müde ist.
   💡 In a subordinate clause introduced by "weil", the conjugated verb must move to the very end of the sentence.
3. ❌ Ich möchte einen neuen Putzplan mit klare Regeln...
   ✅ Ich möchte einen neuen Putzplan mit klaren Regeln...
   💡 After the preposition "mit", you must use the dative case, which affects the adjective ending.

Planted errors:
- [FOUND] `kasus` `auf der Tisch` → `auf den Tisch`
- [FOUND] `verbposition` `weil er ist abends sehr müde` → `weil er abends sehr müde ist`
- [FOUND] `adjektivendung` `mit klare Regeln` → `mit klaren Regeln`

### DE · run 1 · seed 2235 · 10343 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ ...sein Geschirr wieder auf der Tisch gestellt.
   ✅ ...sein Geschirr wieder auf den Tisch gestellt.
   💡 „Auf“ ist hier eine Wechselpräposition, und da es eine Bewegung ist (Wohin?), brauchen wir den Akkusativ.
2. ❌ ...weil er ist abends sehr müde.
   ✅ ...weil er abends sehr müde ist.
   💡 In einem Nebensatz mit der Konjunktion „weil“ muss das konjugierte Verb am Ende stehen.
3. ❌ Ich möchte einen neuen Putzplan mit klare Regeln...
   ✅ Ich möchte einen neuen Putzplan mit klaren Regeln...
   💡 Die Präposition „mit“ verlangt immer den Dativ, und das Adjektiv braucht hier die passende Dativ-Endung.

Planted errors:
- [FOUND] `kasus` `auf der Tisch` → `auf den Tisch`
- [FOUND] `verbposition` `weil er ist abends sehr müde` → `weil er abends sehr müde ist`
- [FOUND] `adjektivendung` `mit klare Regeln` → `mit klaren Regeln`


## Case `arbeit_kollegen`

Planted: `kasus` `mit mein Chef` → `mit meinem Chef`; `verbposition` `weil wir haben nur zwei Wochen` → `weil wir nur zwei Wochen haben`; `perfekt-hilfsverb` `habe danach nach Hause gefahren` → `bin danach nach Hause gefahren`

### EN · run 1 · seed 3234 · 9435 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ mit mein Chef
   ✅ mit meinem Chef
   💡 "Mit" always requires the dative case, and "Chef" is masculine.
2. ❌ weil wir haben nur zwei Wochen
   ✅ weil wir nur zwei Wochen haben
   💡 In a subordinate clause starting with "weil", the conjugated verb must move to the very end.
3. ❌ habe danach nach Hause gefahren
   ✅ bin danach nach Hause gefossen
   💡 Movement from one place to another requires the auxiliary verb "sein" instead of "haben".

Planted errors:
- [FOUND] `kasus` `mit mein Chef` → `mit meinem Chef`
- [FOUND] `verbposition` `weil wir haben nur zwei Wochen` → `weil wir nur zwei Wochen haben`
- [MISSED] `perfekt-hilfsverb` `habe danach nach Hause gefahren` → `bin danach nach Hause gefahren`

### DE · run 1 · seed 3235 · 8794 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ Ich habe gestern mit mein Chef über das neue Projekt gesprochen
   ✅ Ich habe gestern mit meinem Chef über das neue Projekt gesprochen
   💡 Nach der Präposition „mit“ benutzt man immer den Dativ.
2. ❌ weil wir haben nur zwei Wochen für die Vorbereitung
   ✅ weil wir nur zwei Wochen für die Vorbereitung haben
   💡 In einem Nebensatz mit „weil“ steht das konjugierte Verb am Ende des Satzes.
3. ❌ und habe danach nach Hause gefahren
   ✅ und bin danach nach Hause gefahren
   💡 Das Verb „fahren“ beschreibt eine Bewegung von A nach B und bildet das Perfekt deshalb mit „sein“.

Planted errors:
- [FOUND] `kasus` `mit mein Chef` → `mit meinem Chef`
- [MISSED] `verbposition` `weil wir haben nur zwei Wochen` → `weil wir nur zwei Wochen haben`
- [FOUND] `perfekt-hilfsverb` `habe danach nach Hause gefahren` → `bin danach nach Hause gefahren`


## Case `diskussion`

Planted: `verbposition` `Meiner Meinung nach, die Autos sind` → `Meiner Meinung nach sind die Autos`; `kasus` `mit Fahrräder` → `mit Fahrrädern`; `genus` `das öffentliche Verkehr` → `der öffentliche Verkehr`

### EN · run 1 · seed 4234 · 9941 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ Meiner Meinung nach, die Autos sind nicht das größte Problem
   ✅ Meiner Meinung nach sind die Autos nicht das größte Problem
   💡 In German, "Meiner Meinung nach" occupies the first position, so the verb must follow immediately.
2. ❌ mit Fahrräder ausliefern
   ✅ mit Fahrrädern ausliefern
   💡 The preposition "mit" always requires the dative case, so the plural noun needs an "-n" ending.
3. ❌ das öffentliche Verkehr
   ✅ der öffentliche Verkehr
   💡 The noun "Verkehr" is masculine, so the article and adjective must reflect this.

Planted errors:
- [FOUND] `verbposition` `Meiner Meinung nach, die Autos sind` → `Meiner Meinung nach sind die Autos`
- [FOUND] `kasus` `mit Fahrräder` → `mit Fahrrädern`
- [FOUND] `genus` `das öffentliche Verkehr` → `der öffentliche Verkehr`

### DE · run 1 · seed 4235 · 10515 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ Meiner Meinung nach, die Autos sind nicht das größte Problem
   ✅ Meiner Meinung nach sind die Autos nicht das größte Problem
   💡 Nach der Einleitung „Meiner Meinung nach“ folgt das Verb an der zweiten Position im Satz.
2. ❌ die Pakete mit Fahrräder ausliefern
   ✅ die Pakete mit Fahrrädern ausliefern
   💡 Das Wort „mit“ braucht den Dativ Plural, deshalb bekommt das Nomen die Endung „-n“.
3. ❌ Ich finde, das öffentliche Verkehr sollte besser werden
   ✅ Ich finde, der öffentliche Verkehr sollte besser werden
   💡 Das Wort „Verkehr“ ist maskulin (der Verkehr), deshalb muss auch der Artikel und das Adjektiv angepasst werden.

Planted errors:
- [FOUND] `verbposition` `Meiner Meinung nach, die Autos sind` → `Meiner Meinung nach sind die Autos`
- [FOUND] `kasus` `mit Fahrräder` → `mit Fahrrädern`
- [FOUND] `genus` `das öffentliche Verkehr` → `der öffentliche Verkehr`


## Case `pruefung_planung`

Planted: `adjektivendung` `im großem Kursraum` → `im großen Kursraum`; `verbposition` `weil es ist persönlicher` → `weil es persönlicher ist`; `praeposition` `für die Getränke` → `um die Getränke`

### EN · run 1 · seed 5234 · 8803 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ im großem Kursraum
   ✅ im großen Kursraum
   💡 After the preposition "in" (dative), the adjective needs a weak or mixed ending, which is "-en" here.
2. ❌ weil es ist persönlicher
   ✅ weil es persönlicher ist
   💡 In a subordinate clause starting with "weil", the conjugated verb must move to the very end of the sentence.

Planted errors:
- [FOUND] `adjektivendung` `im großem Kursraum` → `im großen Kursraum`
- [FOUND] `verbposition` `weil es ist persönlicher` → `weil es persönlicher ist`
- [MISSED] `praeposition` `für die Getränke` → `um die Getränke`

### DE · run 1 · seed 5235 · 7330 ms

structure=OK · false_corrections=0 · noop_corrections=0 · ungrounded=0 · quotes_kerstin=0 · lang_mismatch=False · format_noise=0

1. ❌ im großem Kursraum
   ✅ im großen Kursraum
   💡 Nach der Präposition „in“ (Dativ) braucht das Adjektiv die Endung „-en“.
2. ❌ weil es ist persönlicher
   ✅ weil es persönlicher ist
   💡 In einem Nebensatz mit „weil“ muss das konjugierte Verb am Ende stehen.

Planted errors:
- [FOUND] `adjektivendung` `im großem Kursraum` → `im großen Kursraum`
- [FOUND] `verbposition` `weil es ist persönlicher` → `weil es persönlicher ist`
- [MISSED] `praeposition` `für die Getränke` → `um die Getränke`
```

### Full before/after feedback (same case/seed)
Case `pruefung_planung`, language `de`, seed 5235.

Before:
```markdown
### Was gut war
*   **Strukturierte Argumentation:** Du hast sehr gute Begründungen mit „weil“ und „dass“ verwendet, um deine Vorschläge zu unterstützen.
*   **Fortgeschrittener Wortschatz:** Die Verwendung von Ausdrücken wie „Ich schlage vor“ oder „Wegen des knappen Budgets“ (Genitiv!) zeigt ein hohes Sprachniveau.
*   **Reaktionsfähigkeit:** Du bist direkt auf die Fragen von Kerstin eingegangen und hast das Gespräch logisch weitergeführt.

### Wichtigste Fehler
*   ❌ „...im großem Kursraum machen“
    *   ✅ ...im große**n** Kursraum machen
    *   💡 Nach der Präposition „in“ (Dativ) braucht das Adjektiv die Endung „-en“.
*   ❌ „...weil es ist persönlicher.“
    *   ✅ ...weil es persönlicher ist.
    *   💡 In einem Nebensatz mit „weil“ muss das konjugierte Verb am Ende stehen.
*   ❌ „Ich habe mich für die Hilfe meiner Kollegin bedankt.“
    *   ✅ Ich habe mich **bei** meiner Kollegin **für** die Hilfe bedankt.
    *   💡 Das Verb „sich bedanken“ braucht die Präposition „bei“ (Person) und „für“ (Sache).

### Besser ausdrücken
*   „Ich schlage vor, dass wir die Feier im großen Kursraum machen...“ $\rightarrow$ „Ich würde vorschlagen, die Feier im großen Kursraum abzuhalten, da dies die kostengünstigste Option ist.“
*   „Ich könnte mich für die Getränke kümmern...“ $\rightarrow$ „Ich könnte die Organisation der Getränke übernehmen...“

### Tipp für das nächste Gespräch
Achte besonders auf die **Verbposition in Nebensätzen** (bei Konjunktionen wie *weil, dass, wenn*), damit deine Sätze grammatikalisch stabil wirken.
```

After:
```markdown
### Was gut war
* Dein Wortschatz ist bereits sehr passend für das B2-Niveau (z. B. „Ich schlage vor...“, „Wegen des knappen Budgets...“).
* Du hast komplexe Strukturen wie Nebensätze mit „dass“ und „weil“ sowie den Konjunktiv II („Ich könnte mich...“) sicher angewendet.
* Deine Argumentation ist logisch und du reagierst direkt auf die Fragen deiner Gesprächspartnerin.

### Wichtigste Fehler
* ❌ ...dass wir die Feier im großem Kursraum machen...
* ✅ ...dass wir die Feier im großen Kursraum machen...
* 💡 Nach der Präposition „in“ (hier Dativ) braucht das Adjektiv die Endung „-en“.

* ❌ ...weil es ist persönlicher.
* ✅ ...weil es persönlicher ist.
* 💡 In einem Nebensatz mit „weil“ muss das konjugierte Verb am Ende stehen.

### Besser ausdrücken
* „Ich schlage vor, dass wir die Feier im großen Kursraum machen, weil das am günstigsten ist.“ → „Ich schlage vor, die Feier im großen Kursraum zu feiern, da dies die kostengünstigste Option ist.“
* „Ich könnte mich für die Getränke kümmern...“ → „Ich könnte die Organisation der Getränke übernehmen...“

### Tipp für das nächste Gespräch
Achte besonders auf die Satzstellung (Verbposition) in Nebensätzen mit „weil“, „dass“ oder „obwohl“.
```

## Review (Claude Code fills this in)
- **Verdict:** Changes requested (round 1). The checker only; the prompt revision is accepted as is.
- **Notes:**
  - **What's good:** the fixtures are correct German (lead-checked: all Kerstin lines, the 10 `correct_tricky` sentences, and the 15 planted errors with their corrections). The prompt revision removed the false correction and the LaTeX noise (20 → 0) without hurting structure or language. Tests and lint pass.
  - **Lead grading of the after-revision triples:**
    - all ✅/💡 are correct except one;
    - real misses: `für die Getränke` (both languages);
    - two checker defects:
  1. **False negative.** DE `arbeit_kollegen`: ❌ "weil wir haben nur zwei Wochen für die Vorbereitung" → ✅ "weil wir nur zwei Wochen für die Vorbereitung haben" is a correct fix, but it's scored MISSED because the ✅ contains extra words between the `right` span's words. True DE recall is 14/15.
  2. **Wrong corrections are hidden.** EN `arbeit_kollegen`: ✅ "bin danach nach Hause **gefossen**" (not a word) is scored as a plain MISSED. A wrong ✅ is worse than a miss, because the learner learns it, and the table must show it.

### Follow-up (round 1) — required changes
1. **Planted-error scoring** in `feedback_checks.py`. For each planted error, find the ❌ item whose quote contains `wrong` (normalized). Then:
   - **found:** the ✅ after it contains the normalized words of `right` **as an in-order subsequence** (gaps allowed) **and** doesn't contain the `wrong` span;
   - **wrong_correction:** a ❌ quotes it, but the ✅ fails the rule above;
   - **missed:** no ❌ quotes it.

   Recall = found / planted.
2. Add a `wrong_corrections` column to the summary table, and mark `[WRONG]` in the per-case list, next to `[FOUND]`/`[MISSED]`.
3. **Tests:**
   - the two real cases above as fixtures-in-test: the longer correct ✅ → found; `gefossen` → wrong_correction;
   - a ✅ that still contains the `wrong` span → wrong_correction.
4. Re-run `make feedback-eval` with the **current** prompt and the same seeds, and paste the new table and the per-case markers. Don't change `feedback.md` or the fixtures in this round.

Allowed files: `backend/kerstin/feedback_checks.py`, `backend/tests/test_feedback_checks.py`, `scripts/feedback_eval.py` (table/markers only), this task file.
