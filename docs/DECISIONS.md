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

## D008 · 2026-11-04 · Accepted 2026-11-05 — Feedback language: configurable
Sameer's call: the 💡 explanations are English or German, chosen in the UI (remembered per browser) and sent with `end`; server default `KERSTIN_FEEDBACK_LANG=en`. Headings, corrections and the tip stay German. Implemented in T017.

## D009 · 2026-11-04 · Superseded by D015 — Default LLM `qwen3:14b` (supersedes D005)
Sameer's call after T001: it is already pulled, ~10 GB resident (light on the shared GPU), warm first token ≈0.1 s after STT. `qwen3:30b-a3b` stays an untested alternative. Known risk: one German grammar slip seen in T001 ("haben sie auch geregnet"). T010 watches reply correctness.

## D010 · 2026-11-04 · Accepted — HTTPS on the LAN via Uvicorn TLS + local openssl CA
Kerstin serves TLS itself (`KERSTIN_TLS_*`). The cert comes from a project-local CA made by `scripts/make_certs.sh`, and each client trusts that CA once. Why: no new software, and nginx on `:80` belongs to other projects, so it stays untouched. mkcert, Caddy and Tailscale were not needed. The default (no TLS vars) is still plain HTTP on 127.0.0.1. **Accepted risk:** with `KERSTIN_HOST=0.0.0.0` anyone on the home LAN (and NordVPN Meshnet peers) can use Kerstin, with no auth. That's fine for a trusted home network; auth comes with T040 before anything goes public.

## D011 · 2026-11-05 · Accepted — Piper `de_DE-thorsten-medium` as default voice (supersedes D006)
Sameer's call after T002. First-sentence TTS: 190 / 338 ms (p50/p90) for medium vs 398 / 1013 ms for high. `high` is still available via `KERSTIN_PIPER_VOICE_PATH`.

## D012 · 2026-11-05 · Accepted — Keep the 768 ms VAD tail and the shared Whisper server
Sameer's call. A shorter tail risks cutting learners off mid-sentence; a second Whisper instance would add a GPU process. T006 cuts latency by speaking the first clause early instead.

## D013 · 2026-11-05 · Open — Latency target vs. these choices
With D011/D012 the realistic end-of-speech → first audio is ≈2.2–2.4 s p50 (VAD tail 768 + STT ~480 + LLM + TTS), not < 1.5 s as `CLAUDE.md` states. Options: (a) accept and restate the target as "server-side first audio < 1.5 s p50", (b) revisit D012 later. Sameer to decide after trying T006.

## D014 · 2026-11-05 · Resolved by D015 — Revisit the conversation model for German correctness
T010 shows `qwen3:14b` makes grammar errors in ≈25 % of replies and gives wrong explanations when asked, which prompt changes don't fix. This breaks D002 (correct B2 German). Candidates already pulled (Ollama reports Apache 2.0, to verify upstream): `gemma4:26b`, `qwen3.6:latest` (MoE), `mistral-nemo:12b-instruct-2407-q8_0`. Compare with `make persona-eval` (lead judges German) + paired bench. Sameer decides; D009 stands until then. 2026-11-05: Sameer approved only `gemma4:26b` for T015. Thermal policy for evals: cool-down at 76 °C → resume at 70 °C, hard abort 80 °C (Sameer has seen no failures below 83 °C; the margin covers temperature rises between per-turn readings).

## D015 · 2026-11-05 · Accepted — Default LLM `gemma4:26b` (supersedes D009)
Sameer's call after T015 (lead graded 60 replies per model). German errors: 3/60 (5 %) vs ≈11/60 (18 %) for `qwen3:14b`. One wrong correction explanation out of 10 correction requests vs 3. No markdown/emoji. Reacts to repetition instead of copying. Takes the opposing view in *Diskussion*. Faster: first audio p50/p90 1384/1661 vs 1630/2171 ms. Cost: ≈17 GB vs 9.8 GB while loaded on the shared GPU (still unloads after `keep_alive`). License per Ollama: Apache 2.0, to be verified upstream (T043).

## D016 · 2026-11-05 · Accepted — Thermal guard = per-turn admission control, read-only
Kerstin checks GPU temperature (`nvidia-smi --query-gpu=temperature.gpu`, cached ≤ 2 s, no background polling) before each GPU job (session start/warm-up, STT+LLM turn, feedback). At ≥ 80 °C she refuses new GPU work until ≤ 74 °C (hysteresis) and tells the learner; a running reply is not aborted (80 → 84 °C margin covers one short reply). Fail-open when `nvidia-smi` is unavailable. No model switch when hot (loading a second model adds load and memory on the shared GPU), no clock/power/fan changes, no touching other processes. Supersedes the "switch to smaller model" idea in the old ROADMAP line.

## D017 · 2026-11-05 · Accepted — Feedback Markdown: own subset renderer, DOM-only, no library
Feedback is rendered by a small in-repo parser (`frontend/markdown.js`) that supports only headings, lists, quotes, rules, paragraphs, bold/italic/code, and builds nodes with `createElement`/`textContent` — never `innerHTML`. Model output can therefore never become HTML, so no sanitizer and no vendored dependency (no license/CDN question). Links, images, tables and raw HTML are shown as plain text by design. Revisit only if feedback needs tables.

## D018 · 2026-11-05 · Accepted — Hints are typed, text-only, outside the conversation
"Wie sagt man …?" hints (T022) are typed (STT is German-only), answered as text in a side panel (not spoken, so the playback queue and mic gate are untouched), and never added to `history` (so they don't appear as learner lines in the feedback). Same model as the conversation; with Ollama's shared `OLLAMA_NUM_PARALLEL=1` a hint can delay a concurrent turn by ≈1 s, which is accepted and bounded by `max_tokens=120`. Ollama's config is not changed (shared with other projects). Round 1 (lead): hints run at temperature 0.2 and answer in exactly two lines (headword with article/plural or verb forms + one example), with no "Alternative" line, because alternatives were often misleading. Measured with `make hint-eval` (20 hold-out queries): 17/20 fully correct, 1/20 teaches an error ("sich auskommen"), so the UI says the answer may contain errors.

## D019 · 2026-11-06 · Accepted — Feedback stays on the chat model; feedback temperature 0.3
T011 measured gemma4:26b at 0.8 vs 0.3 and gemma4:31b at 0.3 (`make feedback-eval`, 20 feedbacks each). 0.3 is equal or better (EN recall 93 % vs 90 %, 0 vs 1 wrong correction) → `KERSTIN_FEEDBACK_TEMPERATURE=0.3`. gemma4:31b: ≈43 s per feedback, GPU up to 79 °C, worse quality (EN 40 % recall) → rejected. More generally, a second Kerstin model occupies one of Ollama's two shared slots and caused another project's model to be evicted during the eval (by a third party's load), so `KERSTIN_FEEDBACK_MODEL` stays unset. The setting and its eviction guard remain for future experiments.

## D020 · 2026-11-06 · Accepted — Mistake log stores categories only, opt-in, deletable
The mistake log (T020) stores per session only date, scenario, feedback language and grammar categories (classified from the 💡 explanation by keyword rules, no LLM). No learner sentence, correction or feedback text is written — data minimisation, and the server has no auth yet (D010/T040). Opt-in per browser (checkbox, default off); "Alle löschen" wipes and VACUUMs the file; rows older than 180 days are pruned. Storing texts (e.g. for a history page, T023) needs its own opt-in and decision. Steering future conversations from the log is T024.
