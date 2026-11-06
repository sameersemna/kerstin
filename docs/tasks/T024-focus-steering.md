# T024 — Focus steering from the mistake log

**Branch:** `task/T024-focus-steering` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code · **Depends on:** T020 merged

## Goal
When the learner has a mistake log (T020), Kerstin naturally creates chances to practise the top 1–2 weak structures. For example, she asks *warum*-questions so the learner answers with *weil*, or talks about the weekend so the learner uses the Perfekt with *sein*. She stays a peer and **never corrects or mentions the focus** (persona contract).

## Spec (outline; the lead finalises it after T020 is merged)
1. **`backend/prompts/focus.json`** (new): category → one German instruction for Kerstin, e.g.
   - `verbposition`: „Stelle ab und zu Warum-Fragen oder frage nach Meinungen, sodass die Person natürlich mit ‚weil‘, ‚dass‘ oder ‚obwohl‘ antworten kann.“;
   - `perfekt_hilfsverb`: „Frage gelegentlich nach Erlebnissen und Wegen in der Vergangenheit (gefahren, gegangen, gekommen).“

   `sonstiges` and `wortwahl` have no instruction.
2. **`PromptStore.system_prompt(scenario_key, focus: list[str] | None = None)`:** appends at most 2 focus lines under a fixed heading, plus the rule „Erwähne den Schwerpunkt nie, korrigiere nicht, bleib natürlich.“ The warm-up must use the identical prompt, so the prefix cache stays valid.
3. **Start:**
   - `start` gains `use_focus: bool`, sent from the T020 checkbox state;
   - the session reads `MistakeLog.summary(days=30)` once (in `to_thread`) and picks the top categories with count ≥ 2 that have an instruction;
   - the UI shows "Heute im Fokus: Verbposition" (text only).
4. **Persona eval:** `scripts/persona_eval.py --focus verbposition`. Before/after on the same seeds:
   - count the replies that invite the structure (lead-graded);
   - check that `reply_checks` stays clean (length, no corrections, no meta talk);
   - Kerstin must not say "Fokus", "Fehler", "üben" or similar meta words (automatic check).

## Files allowed to change
To be listed when the lead finalises the task.

## Acceptance criteria
To be finalised. Minimum: the persona contract holds in the eval, and before/after samples are attached (CLAUDE.md prompt rule).
