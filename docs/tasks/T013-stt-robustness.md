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
- **How tested:**
- **Measurements (if any):**
- **Deviations from spec / extra files touched:**
- **New dependencies (+license):**
- **Open questions:**

## Review (Claude Code fills this in)
- **Verdict:**
- **Notes:**
