# Workflow — Claude Code (lead) ↔ Kilo Code (worker)

```
Sameer ──goal──▶ Claude Code ──task file + short prompt──▶ (Sameer pastes) ──▶ Kilo Code
                      ▲                                                          │
                      └──────── review: diff, tests, acceptance criteria ◀── report + branch
```

## 1. Task files
- Location: `docs/tasks/T0NN-short-name.md`, from `TASK_TEMPLATE.md`.
- One concern per task, finishable in one Kilo session. If a task needs more than ~8 files or > 400 changed lines, split it.
- Acceptance criteria must be checkable: a command, a test name, a measurable number, or an observable behavior.

## 2. The Kilo Code prompt (what Claude Code hands Sameer)
Keep it short — the task file holds the detail:

```
Task T0NN — <title>
Branch: task/T0NN-<short-name> (create from main)
Read: docs/tasks/T0NN-<short-name>.md (full spec), AGENTS.md, .kilocode/rules/kerstin-worker.md
Do: implement exactly the spec. Stay within "Files allowed to change".
Done when: all acceptance criteria pass, `make test` and `make lint` pass, Worker report filled in.
Then commit and stop. Do not merge.
```

Mode hint for Kilo: use **Architect** mode first only if the task file says "design needed"; otherwise **Code** mode.

## 3. Review checklist (Claude Code)
- [ ] Diff touches only allowed files (or deviations are justified in the report)
- [ ] `make test` and `make lint` pass locally
- [ ] Each acceptance criterion verified — not just "report says so"
- [ ] No blocking calls on the event loop; no audio/transcripts written to disk; no telemetry
- [ ] Protocol changes reflected in `docs/PROTOCOL.md` on both client and server
- [ ] New deps listed in `docs/LICENSES.md` with license
- [ ] Latency impact stated if pipeline code changed. A/B latency claims come from **paired** runs (fixed `KERSTIN_LLM_SEED`, same utterances), compared per turn, not two random samples
- [ ] Persona changes come with sample conversations

Outcome:
- **Accept** → merge to main, tick ROADMAP, update STATUS (and DECISIONS if relevant).
- **Revise** → write a follow-up Kilo prompt listing concrete fixes (file, line, expected behavior). Same branch.

## 4. Things only Sameer does
- Running Kerstin and actually speaking with it (quality judgement).
- Anything touching other services on the GB10.
- Decisions recorded as "Open" in `docs/DECISIONS.md`.
- Pulling models > 20 GB.
