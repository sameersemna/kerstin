# T007 — Early STT: transcribe during the VAD silence tail

**Branch:** `task/T007-early-stt` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
Bring end-of-speech → first audio below **1.5 s p50** (D013) **without shortening the 768 ms VAD tail** (D012). The browser sends a *draft* of the utterance ≈ 200 ms into a pause. The server transcribes it while the rest of the tail runs out. If the learner keeps talking, the draft is thrown away. If the pause turns out to be the end of the turn, Kerstin's reply starts from the draft's transcript and skips most of the STT wait.

## Context
- Today (T018): end-of-speech → first audio ≈ **1.7 s p50** = 768 ms VAD tail + 918 ms server (STT ≈ 400–480 ms on the shared whisper.cpp server, LLM first clause ≈ 350, Kokoro ≈ 110). Hiding the STT inside the tail saves ≈ 400 ms → ≈ 1.25–1.35 s.
- Client (`frontend/app.js` `MicVAD.new`): vad-web 0.0.22, legacy Silero, `frameSamples` 1536 at 16 kHz = **96 ms per frame**, `positiveSpeechThreshold` 0.6, `negativeSpeechThreshold` 0.45, `redemptionFrames` 8 (= the 768 ms tail), `minSpeechFrames` 4. `onSpeechEnd(audio)` sends the whole utterance as one binary frame. vad-web calls **`onFrameProcessed(probs, frame)`** for every frame (`probs.isSpeech`, `frame` = Float32Array). That is the hook for building the draft.
- Server: `main.py` hands binary frames to `Session.handle_audio(pcm16)` → `interrupt()` → `turn_id += 1` → `_turn(turn_id, pcm16)`. `_turn` runs:
  1. the gates: too_short, too_quiet (−55 dBFS), thermal, exam `prep`;
  2. STT;
  3. the transcript filter / echo check;
  4. LLM → TTS.
- Whisper is **shared** with other projects (D012). Drafts add requests, so they must be bounded and measured.

## Spec
1. **Protocol** (`docs/PROTOCOL.md`):
   - **Draft frame (client → server, binary):** `b"KDR1"` + `uint32 LE draft_id` + PCM16 (same format as an utterance). It never starts a turn, never interrupts Kerstin, and never increments the turn counter.
   - **Commit (client → server, JSON):** `{"type":"commit","draft":<id>}`, sent **immediately before** the final utterance binary when the draft still covers the whole utterance (no speech after it). The final binary is still sent and still starts the turn exactly as today; the server just reuses the draft's STT for it.
   - Without a commit, or with an unknown or stale id, the server transcribes the final binary normally. **This is the safe default:** any draft bug degrades to today's behaviour, never to a wrong transcript.
   - `session` message gains `"early_stt": true|false`. The client sends drafts only when it is true.
2. **Server** (`session.py`, `main.py`, `config.py`):
   - `KERSTIN_EARLY_STT` (bool, default `true`).
   - `Session.handle_draft(draft_id, pcm16)`: ignored (no STT, logged at DEBUG) when early STT is off, before `session`, while the thermal guard is hot, or during exam `prep`.
     - Run the cheap audio gates (too_short / too_quiet). If they fail, record "gated" and don't call STT.
     - Otherwise start `stt.transcribe` as a task, **without** interrupting the current turn.
     - Keep **only the latest draft**: a new draft cancels the previous task.
     - A draft older than 10 s, or replaced by an uncommitted final binary, is cancelled and dropped.
   - On `commit`: remember the id. On the following binary, if the id matches the latest draft, `_turn` uses the draft's task: await it if still running, and fall back to a fresh STT on the **final** audio if it raised. Gates run on the final audio as today.
   - Echo check, transcript filter and everything after STT are unchanged.
   - `main.py`: binary frames starting with `KDR1` go to `handle_draft`; all others to `handle_audio` as before.
   - Metrics (`TurnMetrics`): `stt_early: bool`, `stt_wait_ms` (time from final binary to transcript ready; ≈ 0 when the draft finished in time). Session-level counters `drafts_sent`, `drafts_committed`, `drafts_wasted_stt` (STT calls whose result was never used), logged at INFO on `end` (counts only, no text).
   - No transcript text in INFO logs (D023).
3. **Client** (new pure module `frontend/early_stt.js` + `app.js` wiring):
   - A small state machine fed by `onFrameProcessed(probs, frame)` and the VAD start/end/misfire events:
     - **Buffer:** while speaking, buffer frames from `onSpeechStart`, plus vad-web's pre-speech pad (keep a 1–2 frame ring buffer before start).
     - **Draft trigger:** after ≥ `minSpeechFrames` speech frames, **2 consecutive frames** with `isSpeech < negativeSpeechThreshold` (≈ 192 ms) → send a draft with the buffered audio. At most **3 drafts per utterance**, and none shorter than 0.5 s.
     - **Draft invalidation:** any later frame with `isSpeech ≥ positiveSpeechThreshold` invalidates it. The learner kept talking, so the next pause may send a new draft.
     - **End of turn:** at `onSpeechEnd`, if the latest draft is still valid, send `commit` then the final binary. Otherwise send just the final binary. `onVADMisfire` resets the state.
   - Respect the existing guards: `examBlocksSpeech()`, the mic gate, speaker mode, and no drafts while `vadInstance` is paused.
   - Node tests for the state machine (frame sequences → draft / invalidate / commit decisions).
4. **Bench** (`scripts/latency_bench.py`):
   - Add `--early-stt`: per utterance, send the draft, wait `vad_tail_ms − 192` ms, then send `commit` + final binary. Without the flag, behaviour is as today.
   - `est. real` stays `first_audio_ms + vad_tail_ms`. `first_audio_ms` is still measured from the final binary, which arrives at the end of the tail.
   - Print `stt_wait_ms` p50/p90 and wasted-STT counts.
5. **Docs:**
   - `docs/ARCHITECTURE.md`: latency budget, plus a short "early STT" paragraph.
   - `docs/STATUS.md`: the latency line.
   - `.env.example`: `KERSTIN_EARLY_STT`.

## Files allowed to change
- `backend/kerstin/session.py`, `main.py`, `config.py`
- `frontend/app.js`, `frontend/early_stt.js` (new), `frontend/tests/early_stt.test.js` (new)
- `scripts/latency_bench.py`, `.env.example`
- `backend/tests/…` (new/updated)
- `docs/PROTOCOL.md`, `docs/ARCHITECTURE.md`, `docs/STATUS.md` (latency line), this task file

## Out of scope / hard rules
- **No change to the VAD thresholds, `redemptionFrames` or `minSpeechFrames`** (D012). No change to the Whisper server, its flags or its systemd unit. No second Whisper instance.
- No speculative LLM or TTS work: only STT runs early.
- Port 8771 only, never 8770. Never touch other projects' services. Check `nvidia-smi` before bench runs and wait if another project is busy; `cool_down()` rule.
- No learner audio or transcripts on disk. Test WAVs are synthesised from fixed text into a scratch dir and not committed.

## Acceptance criteria
- [ ] `make test` and `make lint` pass. Server tests with a fake STT cover:
  - commit reuses the draft (STT called once);
  - a draft without a commit gets a normal STT on the final audio;
  - a new draft cancels the old one;
  - a committed draft whose STT raised → fresh STT on the final audio;
  - stale/unknown commit id → normal path;
  - drafts ignored in `prep`, when thermal is hot and when the feature is off;
  - a gated draft (too quiet) → no STT call;
  - a draft never interrupts a running reply and never changes `turn_id`.
- [ ] Node tests for `early_stt.js` pass (incl. „pause 300 ms then keep talking“ → draft invalidated, final sent without commit).
- [ ] **Latency:** `latency_bench --runs 2` on 8771 with the default voice, with and without `--early-stt`, same seed. Paste both tables. Target: `est. real` p50 **< 1500 ms** with `--early-stt`. Report `stt_wait_ms` p50/p90 and the extra Whisper requests per turn.
- [ ] **Correctness in a real browser path:** headless Chromium with `--use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<wav>`. Use two Piper-synthesised WAVs (fixed sentences, scratch dir):
  - (a) one sentence, then 1.5 s silence → one draft, committed, full transcript, `stt_early=true`;
  - (b) „Ich glaube, dass …“ + a **400 ms pause** + the rest of the sentence + 1.5 s silence → the first draft is invalidated, and the final transcript contains the **whole** sentence (not cut at the pause).
  - Paste the `metrics` and draft counters for both.
- [ ] Whisper load: report drafts sent / committed / wasted per turn over the bench run. Wasted STT ≤ 1 per turn on average.
- [ ] Worker report filled in.

## Worker report (Kilo Code fills this in)
- **Changed files:**
- **How tested:**
- **Measurements (if any):**
- **Deviations from spec / extra files touched:**
- **New dependencies (+license):**
- **Open questions:**

## Review (Claude Code fills this in)
- **Verdict:** accept / revise
- **Notes:**
