# Decision log

Format: ID · date · status (Accepted / Open / Superseded) · decision · why.

## D001 · 2026-11-04 · Accepted — Cascaded pipeline, not speech-to-speech
STT → LLM → TTS instead of an end-to-end voice model. Why: works with what already runs on the GB10 (Whisper, Ollama), every stage swappable, transcripts available for feedback. Cost: ~1–1.5 s turn latency instead of ~0.3–0.5 s.

## D002 · 2026-11-04 · Accepted — Kerstin is a peer, not a tutor
Fellow B2 learner persona (Swedish, lives in Berlin). Speaks **correct** B2-range German; may search for words but makes no deliberate grammar errors (modelling errors would teach them). No corrections during the conversation; feedback only at the end. Why: this is the gap in commercial apps, and it lowers speaking anxiety.

## D003 · 2026-11-04 · Accepted — VAD in the browser
Silero VAD via vad-web on the client; server receives complete utterances. Why: simplest robust turn-taking, no streaming STT needed for v0. Revisit if we want partial transcripts or server-side endpointing.

## D004 · 2026-11-04 · Accepted — STT via existing HTTP server by default
`HttpSTT` against an OpenAI-compatible endpoint; `LocalSTT` optional. Why: Sameer already runs Whisper; CTranslate2 CUDA wheels on aarch64 are uncertain.

## D005 · 2026-11-04 · Superseded by D009 — Default LLM `qwen3:30b-a3b`, thinking off
MoE keeps first-token latency low on GB10 memory bandwidth. To be confirmed by T002; alternatives: `gemma3:12b`, `mistral-small3.2`.

## D006 · 2026-11-04 · Superseded by D011 — Piper `de_DE-thorsten-high` as default TTS
Fast on CPU, offline, German. Kokoro-German evaluated in T012.

## D007 · 2026-11-04 · Open — Kerstin's own "learner flavour"
Should Kerstin occasionally show B2-learner traits beyond word-searching (e.g. asking the user to explain a word, mixing in a Swedish word)? Sameer to decide after using v0.

## D008 · 2026-11-04 · Open — Feedback language
Explanations in English (current) vs German vs configurable.

## D009 · 2026-11-04 · Accepted — Default LLM `qwen3:14b` (supersedes D005)
Sameer's call after T001: it is already pulled, ~10 GB resident (light on the shared GPU), warm first token ≈0.1 s after STT. `qwen3:30b-a3b` stays an untested alternative. Known risk: one German grammar slip seen in T001 ("haben sie auch geregnet"). T010 watches reply correctness.

## D010 · 2026-11-04 · Accepted — HTTPS on the LAN via Uvicorn TLS + local openssl CA
Kerstin serves TLS itself (`KERSTIN_TLS_*`). The cert comes from a project-local CA made by `scripts/make_certs.sh`, and each client trusts that CA once. Why: no new software, and nginx on `:80` belongs to other projects, so it stays untouched. mkcert, Caddy and Tailscale were not needed. The default (no TLS vars) is still plain HTTP on 127.0.0.1. **Accepted risk:** with `KERSTIN_HOST=0.0.0.0` anyone on the home LAN (and NordVPN Meshnet peers) can use Kerstin, with no auth. That's fine for a trusted home network; auth comes with T040 before anything goes public.

## D011 · 2026-11-05 · Accepted — Piper `de_DE-thorsten-medium` as default voice (supersedes D006)
Sameer's call after T002. First-sentence TTS: 190 / 338 ms (p50/p90) for medium vs 398 / 1013 ms for high. `high` is still available via `KERSTIN_PIPER_VOICE_PATH`.

## D012 · 2026-11-05 · Accepted — Keep the 768 ms VAD tail and the shared Whisper server
Sameer's call. A shorter tail risks cutting learners off mid-sentence; a second Whisper instance would add a GPU process. T006 cuts latency by speaking the first clause early instead.

## D013 · 2026-11-05 · Open — Latency target vs. these choices
With D011/D012 the realistic end-of-speech → first audio is ≈2.2–2.4 s p50 (VAD tail 768 + STT ~480 + LLM + TTS), not < 1.5 s as `CLAUDE.md` states. Options: (a) accept and restate the target as "server-side first audio < 1.5 s p50", (b) revisit D012 later. Sameer to decide after trying T006.

## D014 · 2026-11-05 · Open — Revisit the conversation model for German correctness
T010 shows `qwen3:14b` makes grammar errors in ≈25 % of replies and gives wrong explanations when asked, which prompt changes don't fix. This breaks D002 (correct B2 German). Candidates already pulled (Ollama reports Apache 2.0, to verify upstream): `gemma4:26b`, `qwen3.6:latest` (MoE), `mistral-nemo:12b-instruct-2407-q8_0`. Compare with `make persona-eval` (lead judges German) + paired bench. Sameer decides; D009 stands until then.
