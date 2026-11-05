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
- **Changed files:**
- **How tested:**
- **Measurements (if any):**
- **Deviations from spec / extra files touched:**
- **New dependencies (+license):**
- **Open questions:**

## Review (Claude Code fills this in)
- **Verdict:**
- **Notes:**
