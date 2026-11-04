# T002 — Latency baseline (per stage, p50/p90)

**Branch:** `task/T002-latency-baseline` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
One command (`make bench`) prints reliable p50/p90 numbers for every stage of a turn, plus an estimate of the real end-of-speech → first-audio time (including the browser's VAD silence tail). The lead and Sameer can then decide what to cut to get under 1.5 s. This task measures; it doesn't optimize.

## Context
- `docs/ARCHITECTURE.md` → latency budget. `docs/STATUS.md` → T001/T032 numbers: warm server-side first audio 1.2–1.9 s. STT 0.36–0.70 s (shared whisper.cpp server). LLM first token about 0.1 s after STT. First sentence complete about 0.7 s later. Piper `thorsten-high` about 0.65 s for the first sentence.
- Today's `metrics` message can't separate "LLM finished the first sentence" from "TTS finished synthesizing it". This task adds two timestamps for that.
- The VAD silence tail isn't visible to the server. `frontend/app.js` uses `redemptionFrames: 8`. Confirm from the vad-web **0.0.22** source how long one frame is (expected: `frameSamples` 1536 at 16 kHz = 96 ms, so ≈768 ms). Don't guess.
- Model is fixed: `qwen3:14b` (D009). **No model comparisons.**

## Hard rules
- Same as T001/T032: don't touch the Whisper server (`/load` is forbidden), Ollama config, nginx or system settings, and don't pull Ollama models.
- Run your server on **port 8771**. Leave Sameer's 8770 instance alone.
- GPU guard: abort at ≥ 80 °C (reuse the smoke test's thermal guard). Pause ≥ 1 s between turns. Total bench load must stay under ~5 min of turns.
- No audio written to disk. Benchmark utterances are synthesized in memory.

## Spec
1. **Metrics** (`backend/kerstin/session.py`, `TurnMetrics` only):
   - Add `first_sentence_ms`: time from t0 until the consumer receives the first non-empty sentence.
   - Add `tts_first_ms`: duration of the first sentence's `synthesize` call.
   - Leave the existing fields and their meaning unchanged. The change is additive and adds no latency (timestamps only).
   - Update the `metrics` line in `docs/PROTOCOL.md`. `app.js` ignores unknown fields, so don't change it.
2. **Test** (`backend/tests/test_session.py`): extend `test_opener_and_turn` so it asserts the two new fields exist, are ≥ 0, and that `first_sentence_ms ≤ first_audio_ms`.
3. **`scripts/latency_bench.py`** + `make bench`:
   - Reuse helpers by importing from `scripts/smoke_test.py` (same directory): synthesis, resampling, SSL context, thermal guard. Don't copy-paste them. Small refactors inside `smoke_test.py` are allowed if needed; `make smoke` must keep working unchanged.
   - Built-in list of **10 German utterances** at B2 level, ranging from about 2 s to about 10 s of speech. Mix statements, questions, and one with a subordinate clause and a pause comma.
   - CLI: `--url`/`--cafile` (same defaults as smoke), `--runs` (passes over the list, default 2 → 20 measured turns), `--warmup` (default 1 unmeasured turn), `--pause` (default 1.5 s), `--vad-tail-ms` (default: the value confirmed above).
   - Per turn, record from the server `metrics`: `audio_s`, `stt_ms`, `llm_first_token_ms`, `first_sentence_ms`, `tts_first_ms`, `first_audio_ms`, `total_ms`, `sentences`. Also record the transcript and Kerstin's full reply text.
   - Output:
     - (a) a table with p50 / p90 / max per metric;
     - (b) derived stage durations at p50/p90: `stt`, `llm_to_first_token` (= `llm_first_token_ms − stt_ms`), `first_sentence_wait` (= `first_sentence_ms − llm_first_token_ms`), `tts_first`;
     - (c) `est_end_of_speech_to_audio` = `first_audio_ms + vad_tail_ms` at p50/p90, compared with the 1500 ms target;
     - (d) a list of every turn's transcript → reply, so German correctness can be reviewed;
     - (e) GPU temperature at start and end.
   - Print to stdout only. No result files.
4. **Piper voice A/B:**
   - Extend `scripts/get_voice.sh` with an optional quality argument (`high` default, `medium`), so `bash scripts/get_voice.sh medium` fetches `de_DE-thorsten-medium`.
   - Run the bench twice, once per voice, by starting the 8771 server with `KERSTIN_PIPER_VOICE_PATH=voices/de_DE-thorsten-medium.onnx` for the second run.
   - Report `tts_first_ms` for each voice. Sameer judges the sound quality himself; don't decide it.
5. **Makefile:** `bench: ## latency baseline (server must be running)` → `$(PY) scripts/latency_bench.py $(BENCH_ARGS)`, added to `.PHONY`.
6. **Report:** paste both bench outputs (high, medium) into the Worker report, plus the confirmed VAD frame duration with a link or quote from the vad-web 0.0.22 source. Also add a 3-line "where the time goes" summary: the biggest stage first, with numbers.

## Files allowed to change
- `backend/kerstin/session.py` (`TurnMetrics` fields + their two timestamps only)
- `backend/tests/test_session.py`
- `docs/PROTOCOL.md` (`metrics` row only)
- `scripts/latency_bench.py` (new), `scripts/smoke_test.py` (helper refactor only, if needed)
- `scripts/get_voice.sh`
- `Makefile`
- this task file (Worker report only)

## Out of scope
Any optimization: VAD tuning, sentence-splitting changes, prompt/persona changes, model changes, the warm-up (T005), STT changes, and frontend changes.

## Acceptance criteria
- [ ] `make test` and `make lint` pass; `test_opener_and_turn` checks the new metric fields
- [ ] `make smoke` still passes, unchanged
- [ ] `make bench` (against an 8771 server) completes 20 measured turns with 0 errors and prints tables (a)–(e)
- [ ] Bench results reported for both `thorsten-high` and `thorsten-medium`
- [ ] The VAD frame duration is confirmed from the vad-web 0.0.22 source (quote/link in the report)
- [ ] GPU < 80 °C throughout (from bench output)
- [ ] `git diff main --stat` shows only allowed files; no result/audio files written

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
