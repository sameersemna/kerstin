# Status

_Last updated: 2026-11-05 (T013 STT robustness merged)_

## Works on the GB10 (T001, 2026-11-04)
- End-to-end headless: `make smoke` passes. German utterance → whisper.cpp (`:8768`, `language=de`) → Ollama → Piper → WAV over `/ws`.
- Versions: Python 3.12.3 (aarch64), piper-tts 1.8.0 (installs cleanly), Ollama 0.34.2, `think: false` works (no `<think>` text seen).
- Model: **`gemma4:26b`**, the default since D015 (≈17 GB, 100% GPU, `think: false` accepted). Previous default `qwen3:14b` stays available.
- Warm latency (server-side, from receiving the utterance): first audio 1.2–2.2 s. STT 0.36–0.70 s (varies with load on the shared Whisper server), LLM first token +0.1 s, first sentence complete ≈0.7 s later, Piper ≈0.65 s for the first sentence. Cold first turn: ≈8.8 s (model load).
- GPU stayed at 47–59 °C during smoke runs.

- Browser path works (Sameer, 2026-11-04): mic → vad-web (CDN) → reply audio over the SSH tunnel.

- HTTPS on the LAN (T032): Uvicorn TLS with a local CA (`make certs`). Verified with curl and a `wss://` smoke test from the GB10; Sameer's check from the Mac is still pending. Names in the cert: `promaxgb10-6116.fritz.box` (recommended), `.local`, `192.168.178.55`, `localhost`.
- mDNS caveat: avahi advertises the Docker bridge (`172.30.0.1`) for `promaxgb10-6116.local`, so prefer the `.fritz.box` name or the IP.

## Latency baseline (T002, `make bench`, 20 warm turns, qwen3:14b)
| ms (p50 / p90) | STT | LLM 1st token after STT | wait for 1st sentence | TTS 1st sentence | first audio (server) | + VAD tail 768 → est. real |
|---|---|---|---|---|---|---|
| Piper thorsten-**high** | 484 / 652 | 123 / 764 | 454 / 1200 | 398 / 1013 | 1935 / 3345 | **2703 / 4113** |
| Piper thorsten-**medium** | 478 / 669 | 156 / 860 | 554 / 1357 | 190 / 338 | 1881 / 2636 | **2649 / 3404** |

Target < 1500 ms. Biggest stages: VAD tail (768, fixed), STT (~480, shared server), first-sentence decode (~450–550), TTS (190–400).
Since T005: random `seed` per request (`KERSTIN_LLM_SEED` fixes it for benches), and a warm-up on `start` loads the model while the opener plays. Cold first turn: 1.4 s to first audio (was 8.8 s). Warm p50 first audio after T005: 1.8 s server-side.

Since T006: the first clause (≥ 4 words at `,` `;` `:` `–`) is spoken early. Paired A/B (fixed seed): median −379 ms first audio; 0 cost when no clause. Estimated real end-of-speech → audio now ≈ 2.2–2.6 s p50 (D013 open).

T015 latency with `gemma4:26b` (fixed seed, `--runs 2`): first audio p50/p90 1384/1661 ms server-side → est. real 2152/2429 ms with the VAD tail. The T002 table above is the `qwen3:14b` baseline.

## Works (verified in a dev sandbox)
- Unit tests: sentence splitter (abbreviations, ordinals, quotes) and session pipeline with fake STT/LLM/TTS, including barge-in cancel and feedback. `make test` → 173 Python + 23 JS (`node --test`: mic gate, Markdown renderer) passed.
- App starts; `/health`, `/api/scenarios`, `/`, static files served; WebSocket `start` → session + opener text.

## Not yet verified
- `LocalSTT` (faster-whisper): CTranslate2 PyPI wheels for aarch64 may be CPU-only; CUDA may need a source build. Not on the default path.
- True end-of-speech latency, including the browser VAD tail (T002).

## Known limitations
- **Latency over target** once the VAD tail is counted (≈1.8–2.9 s vs < 1.5 s).
- German correctness (T015, lead-graded): `gemma4:26b` makes errors in ≈5 % of replies (3/60), and 1 of 10 correction explanations was wrong ("auf dem Tisch"). Better than `qwen3:14b` (18 %) but not zero; keep checking with `make persona-eval`.
- STT filter (T013): an utterance consisting *only* of "Vielen Dank", "Tschüss" or "Amen" is dropped as a likely Whisper hallucination (whisper.cpp outputs these for clicks/noise even at speech level). Gate threshold −55 dBFS: tune it against the "Pegel" shown in the UI.
- Feedback 💡 explanations in English or German (T017, D008): UI selector "Erklärungen", remembered per browser, sent with `end`; server default `KERSTIN_FEEDBACK_LANG=en`. Feedback quality (T016, `make feedback-eval`, 5 planted-error cases, gemma4:26b, revised prompt): DE 14/15 errors found, 0 wrong corrections; EN 13/15, 1 wrong correction (non-word "gefossen"); 0 false corrections of correct German, 0 ungrounded/Kerstin quotes, 0 LaTeX noise. Fixed preposition verbs (*sich kümmern um*) are the weak spot.
- Feedback runs at temperature 0.3 on the chat model (T011, D019): EN/DE recall 93 % on the planted-error eval, 0 wrong corrections, ≈8.5 s p50. `KERSTIN_FEEDBACK_MODEL` exists (eviction-guarded) but is unset; gemma4:31b was too slow/hot.
- Hint box "Wie sagt man …?" (T022, D018): typed query → 2-line German answer (headword with article/plural or forms + example), text only, not in history/feedback; p50 ≈0.9–1.2 s; a concurrent hint delays a turn by ≈0.7 s (`OLLAMA_NUM_PARALLEL=1`). Quality (`make hint-eval`, 20 hold-out queries): 17/20 fully correct, 1/20 wrong ("sich auskommen mit"); the UI warns that answers may contain errors.
- Feedback is rendered from a Markdown subset by `frontend/markdown.js` (T004, D017; DOM-only, links/images/HTML show as text).
- Echo (T014): speaker mode (default) pauses the mic while Kerstin speaks; interrupt with space bar or "Unterbrechen". Headphone mode keeps voice barge-in. Server drops transcripts ≥ 6 words that are ≥ 80 % Kerstin's last reply (`echo`). Not yet verified by ear without headphones (Sameer's manual check).
- Thermal guard (T030, D016): before each start/turn/feedback the server reads the GPU temperature (cached 2 s, ≈17 ms uncached). At ≥ 80 °C it pauses new GPU work until ≤ 74 °C and the UI shows "GPU zu warm"; a reply already playing finishes. Read-only, fail-open without `nvidia-smi`. `/health` shows `gpu_temp_c` and `thermal`. Verified with a forced threshold, not under real heat.
- Single-user, no auth. Default bind is 127.0.0.1; with `KERSTIN_HOST=0.0.0.0` anyone on the LAN or NordVPN Meshnet can use it (D010, auth comes with T040).
