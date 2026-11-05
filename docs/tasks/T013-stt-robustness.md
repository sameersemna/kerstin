# T013 — STT robustness: energy gate, hallucination filter, no silent drops

**Branch:** `task/T013-stt-robustness` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
Noise, breathing, a cough or a VAD misfire must never turn into a fake learner turn. Whisper hallucinates on silence and noise (German classics: "Untertitel der Amara.org-Community", "Untertitel im Auftrag des ZDF für funk, 2017", "Vielen Dank fürs Zuschauen", "[Musik]", "[BLANK_AUDIO]"), and Kerstin then answers it. After this task, such utterances are dropped and the learner sees "nicht verstanden – bitte wiederholen". Dropped utterances also never reach the LLM or the history.

## Context
- `Session._turn` (`backend/kerstin/session.py`):
  - utterances < `MIN_UTTERANCE_S` (0.35 s) **return silently**: no message, so the UI stays on "du sprichst …" (STATUS known limitation);
  - otherwise STT → if empty, `stt_empty` → else `transcript` + history.
- `frontend/app.js` already handles `stt_empty` ("nicht verstanden – bitte wiederholen").
- whisper.cpp at `:8768` is shared with Sunny. Its binary supports `--suppress-nst` and `--no-speech-thold` as **startup flags**. Whether `/inference` also accepts them **per request** is unknown, so test it (step 4). **Never change the server's startup flags.**
- Privacy (CLAUDE.md): transcripts must not end up on disk. Log files may be persisted by systemd later, so **never log transcript text at INFO or above**.

## Spec
1. **Energy helper** (`backend/kerstin/audio.py`): `pcm16_rms_dbfs(pcm: bytes) -> float`.
   - Pure Python (`array('h')`), no numpy.
   - Returns dBFS relative to full scale 32768, with `-120.0` for empty or all-zero input.
   - Must take < 5 ms for a 10 s utterance. Measure it and put the number in the report.
2. **Hallucination filter** (`backend/kerstin/stt_filter.py`, new, pure functions):
   - `clean_transcript(text: str) -> tuple[str, str | None]` returns `(cleaned_text, drop_reason)`. `drop_reason` is `None` when the text is kept.
   - Strip non-speech tags: `[...]`, `(...)` and `*...*` that contain only tag words (`Musik`, `Applaus`, `Lachen`, `BLANK_AUDIO`, `Stille`, `Geräusche`, `music`, `silence`; case-insensitive). If nothing is left → `("", "tags_only")`.
   - Known-hallucination list (normalized: lowercase, punctuation stripped):
     - **substring** markers that are never real conversation: `amara.org`, `untertitel im auftrag`, `untertitelung des zdf`, `untertitelung im auftrag`, `copyright wdr`, `swr 20`, `zdf für funk`, `www.`. Don't use plain `untertitel der` / `untertitelung`: learners do talk about subtitles ("Die Untertitel der Serie waren schlecht" must be **kept**; add this as a test);
     - **whole-utterance** matches only (the full transcript equals one of these): `vielen dank fürs zuschauen`, `danke fürs zuschauen`, `bis zum nächsten mal`, `tschüss`, `untertitel`.
     - A match → `("", "hallucination")`.
   - Repetition loops: if one word or 2–4-word n-gram repeats ≥ 4 times in a row, keep the first occurrence only and report the reason `"repetition_trimmed"`. The text is kept, not dropped.
   - Keep the lists as module constants with a comment to extend them from real observations.
3. **Session** (`session.py` `_turn`, plus `Deps` fields set in `main.py`):
   - (a) Short utterance (< `MIN_UTTERANCE_S`): send `stt_empty` with `"reason": "too_short"` instead of returning silently.
   - (b) **Energy gate:** if `pcm16_rms_dbfs(pcm) < deps.stt_min_rms_dbfs` (setting `stt_min_rms_dbfs: float = -55.0`), send `stt_empty` with `"reason": "too_quiet"` and **skip the STT call**. That saves a request to the shared Whisper server.
   - (c) After STT: if `deps.stt_filter` (setting `stt_filter: bool = True`), run `clean_transcript`. If the result is empty, send `stt_empty` with `"reason"` set to the filter reason (or `"empty"`) and don't touch history.
   - (d) Add `audio_dbfs` (rounded to 1 decimal) to `TurnMetrics`. Log one INFO line per dropped utterance with the reason and dBFS only, never the text; the text is allowed at DEBUG.
   - Default behavior for normal speech is unchanged. Latency added must be < 5 ms.
4. **Per-request whisper options** (`backend/kerstin/stt.py`, `WhisperCppSTT` only):
   - Test (a few normal `/inference` requests, never `/load`) whether this server honors per-request `suppress_nst` / `suppress_non_speech` and `no_speech_thold`. Compare the output on the noise samples from step 6 with and without the field.
   - If one demonstrably changes the output, add an opt-in setting (`stt_suppress_nst: bool = False`, plus `stt_no_speech_thold: float | None = None`), send the field only when set, and add a MockTransport test.
   - If it has no effect, add nothing and report the finding.
5. **Protocol + UI:**
   - `docs/PROTOCOL.md`: `stt_empty` gains an optional `reason` (`too_short` | `too_quiet` | `tags_only` | `hallucination` | `empty`), and `metrics` gains `audio_dbfs`.
   - `frontend/app.js`: show `audio_dbfs` as one extra line in the metrics panel ("Pegel: −23.4 dBFS"), so Sameer can see his real mic level. **Nothing else in `app.js` changes.**
6. **Evidence** (shared Whisper server, at most ~20 requests in total):
   - Generate in memory, at 16 kHz Int16: 3 s digital silence; 3 s white noise at −60, −45 and −35 dBFS; 3 s of a 50 Hz hum at −40 dBFS; and 1.5 s of clicks (short spikes).
   - Send each to `/inference` directly (as `WhisperCppSTT` does) and record the raw transcript.
   - Then run each through the new gate + filter, and record what Kerstin would do (dropped/kept + reason).
   - Also run `make smoke` and paste the `audio_dbfs` of the Piper test utterance.
   - Put everything in a table in the report. Don't write audio to disk.
7. **`.env.example`:** commented lines for `KERSTIN_STT_FILTER`, `KERSTIN_STT_MIN_RMS_DBFS` (and the step-4 settings if they were added), with one-line explanations. Note that the dBFS default must be tuned against the real mic level shown in the UI.

## Tests (no network)
- `backend/tests/test_stt_filter.py`: every known hallucination string (with punctuation/case variants) is dropped; tags-only is dropped; a mixed `"[Musik] Ich war gestern im Kino."` keeps the sentence; a normal sentence containing "Tschüss" mid-text ("Ich habe tschüss gesagt und bin gegangen.") is **kept**; the repetition trim works; an empty string is handled.
- `backend/tests/test_audio.py` (new or existing): rms of zeros = −120; a full-scale square wave ≈ 0 dBFS; a half-amplitude wave ≈ −6 dBFS (±0.5).
- `backend/tests/test_session.py`:
  - a short utterance sends `stt_empty` with `too_short`;
  - a quiet utterance sends `too_quiet` and the STT fake is **not called**;
  - an STT fake returning "Untertitel der Amara.org-Community" sends `stt_empty`/`hallucination`, and neither history nor the LLM is touched;
  - normal speech is unchanged and `metrics` includes `audio_dbfs`.
  - Existing tests that use `PCM_1S` of zeros will now hit the energy gate. Give them real non-silent PCM (e.g. a sine) or set `stt_min_rms_dbfs` low in their `Deps`. Don't weaken any assertion.

## Hard rules
Port 8771 for any server, leave 8770 alone. **No `/load`, no change to the whisper-server startup flags or its systemd unit.** At most ~20 extra `/inference` requests for step 4 + 6. No Ollama config changes, no model pulls, thermal guard. No audio or transcripts on disk; no transcript text in INFO logs.

## Files allowed to change
- `backend/kerstin/audio.py`, `backend/kerstin/stt_filter.py` (new), `backend/kerstin/session.py` (`_turn`, `TurnMetrics`, `Deps`), `backend/kerstin/main.py` (Deps wiring), `backend/kerstin/config.py`, `backend/kerstin/stt.py` (step 4 only, `WhisperCppSTT` only)
- `backend/tests/test_stt_filter.py` (new), `backend/tests/test_audio.py`, `backend/tests/test_session.py`, `backend/tests/test_stt.py` (step 4 only)
- `docs/PROTOCOL.md` (`stt_empty`, `metrics` rows only), `frontend/app.js` (metrics line only), `.env.example`
- this task file (Worker report only)

## Out of scope
A Whisper initial prompt, changing VAD settings, server-side VAD, re-ask/voice prompts from Kerstin, a second STT instance (D012), LLM/persona changes.

## Acceptance criteria
- [ ] `make test` and `make lint` pass; all tests listed above exist
- [ ] The evidence table (step 6) shows raw Whisper output vs the gate/filter decision for every sample, and no noise sample reaches the LLM
- [ ] `make smoke` passes; the smoke utterance is kept (not gated); its `audio_dbfs` is reported
- [ ] Short/quiet/hallucinated utterances produce `stt_empty` with a reason. No silent returns remain in `_turn`.
- [ ] `pcm16_rms_dbfs` is < 5 ms for 10 s of audio (number in the report); no transcript text at INFO
- [ ] Step-4 finding reported (honored or not, with evidence)
- [ ] `git diff main --stat` shows only allowed files

## Worker report (Kilo Code fills this in)
- **Changed files:**
  - `backend/kerstin/audio.py` — `pcm16_rms_dbfs()` using `array('h')` and `math.sumprod` on Python 3.12+ (array/map fallback on 3.11); empty/all-zero returns `-120.0`.
  - `backend/kerstin/stt_filter.py` (new) — pure `clean_transcript()`: tag stripping (`[...]`, `(...)`, `*...*` containing only non-speech tag words), normalized substring/whole-utterance hallucination lists, and first-clause repetition trimming (1–4-word n-grams repeated ≥ 4 times; text kept with `repetition_trimmed`).
  - `backend/kerstin/session.py` — `Deps.stt_min_rms_dbfs` / `Deps.stt_filter`, `TurnMetrics.audio_dbfs`, `_turn()` sends `stt_empty` with `too_short`, `too_quiet`, the filter reason or `empty`; energy gate skips STT; dropped utterances never enter history or the LLM; INFO logs contain only reason + dBFS.
  - `backend/kerstin/main.py` — passes the two new settings into `Deps`.
  - `backend/kerstin/config.py` — `stt_min_rms_dbfs: float = -55.0`, `stt_filter: bool = True`.
  - `backend/tests/test_audio.py` (new) — empty/zeros = −120, full-scale square ≈ 0 dBFS, half amplitude ≈ −6 dBFS.
  - `backend/tests/test_stt_filter.py` (new) — every known hallucination with case/punctuation variants, tags-only, mixed tag + sentence, “Die Untertitel der Serie …” kept, mid-sentence “tschüss” kept, repetition trimmed, three repeats kept, empty handled.
  - `backend/tests/test_session.py` — non-silent sine `PCM_1S`, short → `too_short` without STT, quiet → `too_quiet` without STT, hallucination → `stt_empty`/`hallucination` without LLM or history, normal metrics include `audio_dbfs`.
  - `docs/PROTOCOL.md` — `stt_empty` optional reasons and `metrics.audio_dbfs`.
  - `frontend/app.js` — one extra `Pegel: … dBFS` line in the metrics panel only.
  - `.env.example` — commented `KERSTIN_STT_MIN_RMS_DBFS` / `KERSTIN_STT_FILTER` with the mic-level tuning note.
  - `stt.py` / `test_stt.py` were **not** changed: the step-4 per-request fields had no effect (see below).
  - `persona.md`, scenarios and the default model were not touched.
- **How tested:**
  - `make test` → **89 passed**; `make lint` → `All checks passed!`.
  - RMS helper: 10 s of 440 Hz sine, 30 runs after warm-up: **4.579 ms avg** (min 4.566, max 4.622) — under 5 ms.
  - Evidence: 6 baseline `/inference` requests (3 s silence, white noise −60/−45/−35 dBFS, 50 Hz hum −40 dBFS, 1.5 s clicks) + 7 per-request field requests = **13 requests**; no `/load`, no server flags changed.
  - Step 4: `suppress_nst`, `suppress_non_speech` and `no_speech_thold=0.6` all returned HTTP 200 with the **same** transcript as the baseline on silence, clicks and the −35 dBFS noise. No opt-in settings were added.
  - `make smoke` on 8771 (2 turns, whispercpp, shared server) → exit 0; the Piper utterance was kept; its `audio_dbfs` was **−17.4** (turn 1 and turn 2). Total evidence + smoke `/inference` requests: **15**.
  - INFO log check: the smoke server logged only `turn 1/2 metrics {…}` and HTTP request lines; no transcript text. Drop logging is reason + dBFS only (`turn N dropped: reason (audio_dbfs=…)`).
  - Thermal: evidence run 45→55 °C; smoke 46→56 °C; never ≥ 80 °C. 8770 was not started or touched; no audio/transcript files written.
- **Measurements (if any):**
  - Gate + filter evidence table (raw transcript from the shared whisper.cpp, then the decision Kerstin would take):

    | sample | target | measured dBFS | raw transcript | gate | filter | final |
    |---|---|---|---|---|---|---|
    | silence 3s | 3 s digital silence | −120.0 | Vielen Dank. | drop (too_quiet) | drop (hallucination) | dropped: too_quiet |
    | white −60 dBFS | 3 s white noise | −60.0 | Amen. | drop (too_quiet) | drop (hallucination) | dropped: too_quiet |
    | white −45 dBFS | 3 s white noise | −45.0 | Amen. | pass | drop (hallucination) | dropped: hallucination |
    | white −35 dBFS | 3 s white noise | −35.0 | Untertitelung des ZDF, 2020 | pass | drop (hallucination) | dropped: hallucination |
    | hum 50 Hz −40 dBFS | 3 s 50 Hz hum | −40.0 | Vielen Dank. | pass | drop (hallucination) | dropped: hallucination |
    | clicks 1.5 s | 1.5 s short spikes | −17.8 | Vielen Dank. | pass | drop (hallucination) | dropped: hallucination |

    No noise sample reaches the LLM. The table shows the filter result on the raw transcript even when the gate would drop first, for transparency.

  - Step-4 per-request fields:

    | sample | extra field(s) | status | raw transcript | vs baseline |
    |---|---|---|---|---|
    | silence 3s | suppress_nst=true | 200 | Vielen Dank. | same |
    | silence 3s | suppress_non_speech=true | 200 | Vielen Dank. | same |
    | silence 3s | no_speech_thold=0.6 | 200 | Vielen Dank. | same |
    | white −35 dBFS | suppress_nst=true, no_speech_thold=0.6 | 200 | Untertitelung des ZDF, 2020 | same |
    | clicks 1.5s | suppress_nst=true | 200 | Vielen Dank. | same |
    | clicks 1.5s | suppress_non_speech=true | 200 | Vielen Dank. | same |
    | clicks 1.5s | no_speech_thold=0.6 | 200 | Vielen Dank. | same |

    Finding: all three fields are accepted (no HTTP error) but ignored by this server/version; no setting added.
  - Smoke: `audio_dbfs = −17.4` dBFS (turn 1 and turn 2), kept; no `stt_empty`.
- **Deviations from spec / extra files touched:**
  - **Hallucination list extension:** the shared server returned `Vielen Dank.` on silence/hum/clicks and `Amen.` on −60/−45 dBFS white noise. The spec's literal whole-utterance list would keep the −45 dBFS noise, hum and clicks, violating “no noise sample reaches the LLM”. Following the “extend these lists from real observations” instruction, `vielen dank` and `amen` were added as whole-utterance matches. Trade-off: a learner whose entire utterance is exactly “Vielen Dank.” or “Amen.” is now dropped; the lead may want to review this.
  - Step 4 needed no code, so `stt.py` / `test_stt.py` were left untouched.
  - The evidence requests went directly to `/inference`, bypassing the client VAD, exactly as step 6 asks. The smoke used the local `.env` configuration (qwen3:14b, high voice, whispercpp, TLS from `.env`) on 8771; no model pulls.
  - No other files touched.
- **New dependencies (+license):** None in the product code. The temporary evidence script used NumPy only in `/tmp` (already installed); the shipped code uses only stdlib (`array`, `math`, `re`).
- **Open questions:**
  - `KERSTIN_STT_MIN_RMS_DBFS=-55.0` is a starting point; Sameer should tune it against the new UI “Pegel” line on his real microphone.
  - The “Vielen Dank.” / “Amen.” whole-utterance drops are a deliberate false-positive trade-off for noise; the list may need more real-world entries (and possibly a review of these two).
  - The UI shows `Pegel: <value> dBFS` for kept turns; dropped turns show the existing “nicht verstanden – bitte wiederholen” path.

## Review (Claude Code fills this in)
- **Verdict:**
- **Notes:**
- **Verdict:** accept (2026-11-05)
- **Notes:**
  - Diff limited to allowed files. `make test` (89) and `make lint` are clean. No silent returns remain in `_turn`. INFO logs carry reason + dBFS only. Tests were strengthened, not weakened (`PCM_1S` is now a 440 Hz sine; the STT call count is asserted for the gate).
  - Evidence: whisper.cpp (large-v3, no `-l`/VAD flags) answers almost any non-speech with "Vielen Dank." / "Amen." / "Untertitelung des ZDF, 2020". Per-request `suppress_nst`/`no_speech_thold` are ignored by this server.
  - Kilo added `vielen dank` and `amen` as whole-utterance drops: **justified**. Clicks at −17.8 dBFS (same level as real speech, −17.4) produced "Vielen Dank.", so no level rule can separate them. Cost: a learner saying *only* "Vielen Dank." sees "nicht verstanden"; longer phrases pass.
  - `pcm16_rms_dbfs` runs on the event loop: ≈4.6 ms per 10 s, ≈2 ms for a typical 4 s utterance. Acceptable; move it to a thread if utterances get longer.
  - Follow-up idea (not now): show the drop reason in the UI ("zu leise" vs "nicht verstanden").
