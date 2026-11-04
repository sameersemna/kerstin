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

## D005 · 2026-11-04 · Accepted — Default LLM `qwen3:30b-a3b`, thinking off
MoE keeps first-token latency low on GB10 memory bandwidth. To be confirmed by T002; alternatives: `gemma3:12b`, `mistral-small3.2`.

## D006 · 2026-11-04 · Accepted — Piper `de_DE-thorsten-high` as default TTS
Fast on CPU, offline, German. Kokoro-German evaluated in T012.

## D007 · 2026-11-04 · Open — Kerstin's own "learner flavour"
Should Kerstin occasionally show B2-learner traits beyond word-searching (e.g. asking the user to explain a word, mixing in a Swedish word)? Sameer to decide after using v0.

## D008 · 2026-11-04 · Open — Feedback language
Explanations in English (current) vs German vs configurable.
