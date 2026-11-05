# T005 — Model warm-up on session start + random seed per request

**Branch:** `task/T005-warmup-seed` · **Mode:** Code · **Owner:** Kilo Code · **Reviewer:** Claude Code

## Goal
1. When the learner presses "Gespräch starten" and the model was unloaded (idle > `keep_alive`), the first learner turn no longer waits ~7 s for the model to load.
2. Kerstin stops giving word-for-word identical replies to identical input across sessions.

## Context
- Cold first turn: `llm_first_token_ms` ≈ 7.1–7.4 s vs ≈ 0.5 s warm (T001, T032 review). The model loads only when the first learner utterance arrives.
- The lead verified (T002 review) that Ollama 0.34.2 **samples deterministically when no `seed` is sent**: the same messages give the same output even at `temperature` 0.8. And `qwen3:14b` gives the same reply to a repeated sentence even with a different history. Today `llm.py` sends no seed.
- `keep_alive` (default `10m`) must still let the model unload when idle. The warm-up only moves the load earlier; it doesn't keep the model resident any longer.

## Hard rules
- Same as before: port **8771** for test servers; don't touch 8770, the Whisper server (`/load` forbidden), or Ollama config; no model pulls.
- **Don't force-unload the model** (`keep_alive: 0`): other tools may be using `qwen3:14b`. To test a cold start, wait until `ollama ps` no longer lists it (keep_alive expiry), and do other work in the meantime.
- Thermal guard as in the smoke test.

## Spec
1. **Seed** (`backend/kerstin/llm.py`, `backend/kerstin/config.py`):
   - New setting `llm_seed: int | None = None`.
   - In `OllamaLLM._payload`: if `llm_seed` is set, send `options.seed = llm_seed` (reproducible benches). Otherwise send a fresh `random.randrange(1, 2**31)` per request.
   - This applies to `stream_chat` and `chat`. No latency impact.
2. **Warm-up** (`llm.py`, `session.py`, `config.py`):
   - New setting `llm_warmup: bool = True`.
   - `OllamaLLM.warmup(messages: list[Message]) -> None`: a non-streaming `POST /api/chat` with the given messages, `num_predict: 1`, the same `model`, `keep_alive`, `num_ctx` and `think` as normal requests. This loads the model and caches the prompt prefix. It must never raise: log a warning on any error, including timeouts, and return.
   - `Session.start()`: if `llm_warmup` is on, start `asyncio.create_task(self.deps.llm.warmup([system, opener-as-assistant]))` **before** speaking the opener, so it runs while the opener is synthesized and played. Don't await it in `start()`.
   - Keep a reference on the session. `close()` cancels it if still running.
   - A learner turn that arrives while the warm-up is still running just proceeds; Ollama queues it. Don't add waiting logic.
   - Pass the setting through `Deps` (e.g. `Deps.llm_warmup: bool = True`, set in `main.py` from settings). Keep `Session` free of global settings.
3. **Tests** (no network):
   - `backend/tests/test_llm.py` (new), using `httpx.MockTransport` for `OllamaLLM`:
     - (a) without `llm_seed`, two payloads have `options.seed` set and different;
     - (b) with `llm_seed=42`, `options.seed == 42`;
     - (c) `warmup` sends `num_predict: 1`, `stream: false` and the given messages;
     - (d) `warmup` swallows an HTTP 500 and a `httpx.ConnectError`.
     - Allow an injected client: `OllamaLLM(s, client: httpx.AsyncClient | None = None)`, same pattern as `WhisperCppSTT`.
   - `backend/tests/test_session.py`:
     - add `warmup` to `FakeLLM` and record its calls;
     - new test: `start()` triggers exactly one warm-up with the system prompt + opener, and the opener is still sent;
     - new test: with `llm_warmup=False` there's no warm-up call;
     - new test: a `warmup` that hangs (`asyncio.sleep(10)`) doesn't delay the opener, and `close()` cancels it.
4. **Smoke test:** add `--first-delay SECONDS` (default `0`) to `scripts/smoke_test.py`. It sleeps after the opener and before turn 1, simulating the learner thinking. Default behavior is unchanged.
5. **`.env.example`:** add commented `KERSTIN_LLM_WARMUP=true` and `# KERSTIN_LLM_SEED=` lines with one-line explanations. Note that a fixed seed is for benches only.
6. **Measure:**
   - (a) **Cold:** once `ollama ps` doesn't list `qwen3:14b`, start the 8771 server and run `smoke_test.py --url wss://localhost:8771/ws --first-delay 6`. Report turn 1 `llm_first_token_ms` and `first_audio_ms`, and compare with T001's cold 7400 / 8781 ms.
   - (b) **Warm:** run `make bench` with `BENCH_ARGS="--runs 1"` against 8771. Report the p50 `first_audio_ms` (the warm path must not get slower: T002 high p50 was 1935 ms), and paste the (d) reply list showing that replies to identical sentences now differ between passes. Use `--runs 2` if you need two passes for that.
   - Paste `ollama ps` before and after.

## Files allowed to change
- `backend/kerstin/llm.py`, `backend/kerstin/config.py`, `backend/kerstin/session.py` (`start`/`close`/`Deps` only), `backend/kerstin/main.py` (pass `llm_warmup` into `Deps` only)
- `backend/tests/test_llm.py` (new), `backend/tests/test_session.py`
- `scripts/smoke_test.py` (`--first-delay` only)
- `.env.example`
- this task file (Worker report only)

## Out of scope
VAD, Piper voice, STT, prompt/persona changes, keeping the model loaded longer, `/api/ps` checks, and protocol changes.

## Acceptance criteria
- [ ] `make test` and `make lint` pass; the tests from spec step 3 exist and pass
- [ ] `make smoke` passes unchanged (no `--first-delay`)
- [ ] Cold-start run: turn 1 `llm_first_token_ms` < 1500 ms with `--first-delay 6` (T001 cold: 7400 ms)
- [ ] Warm bench p50 `first_audio_ms` is not worse than T002 by more than ~10 %
- [ ] Bench reply list shows different replies to the same utterance in different passes
- [ ] The model still unloads after `keep_alive`: `ollama ps` shows the normal `UNTIL` countdown, not "Forever"
- [ ] `git diff main --stat` shows only allowed files

## Worker report (Kilo Code fills this in)
- **Changed files:**
  - `backend/kerstin/llm.py` — optional injected `httpx.AsyncClient`; `_payload` now always sends `options.seed` (fixed `llm_seed` or a fresh `random.randrange(1, 2**31)`); new `warmup()` does a non-streaming `/api/chat` with `num_predict: 1` and swallows/logs every error.
  - `backend/kerstin/config.py` — `llm_seed: int | None = None` and `llm_warmup: bool = True`.
  - `backend/kerstin/session.py` — `Deps.llm_warmup`, `_warmup_task`; `start()` creates the warm-up (system prompt + opener as assistant) before speaking the opener; `close()` cancels and awaits it.
  - `backend/kerstin/main.py` — passes `settings.llm_warmup` into `Deps`.
  - `backend/tests/test_llm.py` (new) — random vs fixed seed, warm-up payload, and warm-up error swallowing (500, ConnectError, ReadTimeout).
  - `backend/tests/test_session.py` — `FakeLLM.warmup`, three new tests (warm-up args, disabled warm-up, hanging warm-up does not block opener and is cancelled by `close()`).
  - `scripts/smoke_test.py` — `--first-delay` only (default 0; default behavior unchanged).
  - `.env.example` — commented `KERSTIN_LLM_WARMUP=true` and `KERSTIN_LLM_SEED=`.
  - `docs/tasks/T005-warmup-seed.md` — Worker report only.
- **How tested:**
  - `make test` → 30 passed; `make lint` → `All checks passed!`.
  - `make smoke` with no flags still exits 0 (turn 1/2 `llm_first_token_ms` 549/555 ms on a warm model).
  - **Cold:** confirmed `qwen3:14b` was absent from `ollama ps`, started Kerstin on **8771** (TLS, `KERSTIN_HOST=0.0.0.0`), ran `smoke_test.py --url wss://localhost:8771/ws --first-delay 6`, then checked `ollama ps` again.
  - **Warm:** two separate `make bench BENCH_ARGS="--runs 1"` invocations against 8771 (10 measured turns each, fresh WS session each) and compared the reply lists. Each run had 0 errors. GPU guard before every turn; max observed 68 °C.
  - No Whisper `/load`, no Ollama config changes, no model pulls, no forced unload. 8770 was never started or touched.
  - No audio or result files written; utterances are synthesized in memory.
- **Measurements (if any):**
  - **Cold turn 1:** `llm_first_token_ms` **563 ms** (T001 cold: 7400 ms) and `first_audio_ms` **1688 ms** (T001 cold: 8781 ms); `stt_ms=463`, `first_sentence_ms=1155`, `tts_first_ms=528`. The 6 s learner pause was enough for the warm-up load.
  - **Warm p50 `first_audio_ms`:** run A **1798 ms**, run B **1840 ms** (T002 high p50: 1935 ms) — not slower; both are slightly better.
  - `ollama ps` after the cold run and at the end: `qwen3:14b`, 9.8 GB, 100% GPU, context 8192, **“9 minutes from now”** (normal `keep_alive` countdown, not “Forever”).
  - Same utterance, different fresh sessions (run A vs run B):
    - A: “Ich wohne seit drei Jahren in Berlin.” → “Schön, dass du in Berlin bist! Ich lebe seit zwei Jahren hier und finde die Stadt sehr interessant. Magst du Berlin?”
    - B: “Ich wohne seit drei Jahren in Berlin.” → “Schön, dass du hier bist! Berlin ist eine tolle Stadt, aber nicht immer leicht zu finden. Wie bist du hierher gekommen? Aus welchem Land?”
    - All other utterances also differ between A and B.
  - GPU: cold 62→53 °C; warm A 61→67 °C; warm B 65→68 °C.
- **Deviations from spec / extra files touched:**
  - **Reply comparison used two separate `--runs 1` bench invocations, not one `--runs 2`.** Within a single session, when the identical user turn is repeated immediately after the model's answer, `qwen3:14b` copies its previous answer despite a new random seed (verified with the exact prompt and several seeds). The user-facing case is a new session, where the seed does change the reply; two fresh sessions show the difference. A single `--runs 2` list therefore still repeats by in-context copying. `scripts/latency_bench.py` is not in T005's allowed files, so I did not change it to restart the session per pass.
  - The cold run used the TLS URL and the existing `certs/` from T032; the server was on 8771 only.
  - No other files touched.
- **New dependencies (+license):** None. `random` is stdlib; no new packages.
- **Open questions:**
  - Should a future task make `latency_bench.py --runs N` start a fresh session per pass, so one output can demonstrate cross-pass reply variation? Out of scope here.
  - Within a session, repeated identical learner turns still produce the same answer because the model copies its previous turn; that is model behaviour, not the seed. Across sessions the seed works as intended.

### Cold-start smoke (turn 1)

```text
Waiting 6.0 s before turn 1 ...
GPU before turn 1: 62 °C
[  2885 ms] {"type": "metrics", "turn": 1, "audio_s": 4.79, "stt_ms": 463, "llm_first_token_ms": 563, "first_sentence_ms": 1155, "tts_first_ms": 528, "first_audio_ms": 1688, "total_ms": 2876, "sentences": 3}
GPU after turn 1: 53 °C
Summary
turn   stt_ms  llm_1st_ms  srv_audio_ms  cli_audio_ms  total_ms  gpu_before  gpu_after
--------------------------------------------------------------------------------------
   1      463         563          1688          1696      2876       62 °C      53 °C
   2      445         546          1567          1578      3139       53 °C      54 °C
```

### `ollama ps`

Before the cold run (no `qwen3:14b`):

```text
NAME           ID              SIZE      PROCESSOR    CONTEXT    UNTIL             
llama3.2:1b    baf6a787fdff    4.5 GB    100% GPU     131072     20 hours from now
```

After the cold run:

```text
NAME           ID              SIZE      PROCESSOR    CONTEXT    UNTIL              
llama3.2:1b    baf6a787fdff    4.5 GB    100% GPU     131072     20 hours from now     
qwen3:14b      bdbd181c33f2    9.8 GB    100% GPU     8192       9 minutes from now
```

Final (after both warm benches):

```text
NAME           ID              SIZE      PROCESSOR    CONTEXT    UNTIL              
llama3.2:1b    baf6a787fdff    4.5 GB    100% GPU     131072     24 hours from now     
qwen3:14b      bdbd181c33f2    9.8 GB    100% GPU     8192       9 minutes from now
```

### Warm bench — run A (`--runs 1`)

```text
(a) Server metrics (n=10)
metric                       p50       p90       max
----------------------------------------------------
audio_s                     4.66      7.76     10.10
stt_ms                       495       668       779
llm_first_token_ms           603       827       905
first_sentence_ms           1296      2079      2285
tts_first_ms                 512      1220      1880
first_audio_ms              1798      3315      4184
total_ms                    3626      4430      6075
sentences                      3         3         4

(b) Derived stages (ms)
stage                        p50       p90
------------------------------------------
stt                          495       668
llm_to_first_token           110       130
first_sentence_wait          518      1502
tts_first                    512      1220

(c) Estimated end-of-speech -> first audio (first_audio_ms + 768 ms VAD tail)
    p50: 2566 ms    p90: 4083 ms    target: 1500 ms
    vs target: p50 +1066 ms    p90 +2583 ms

(d) Turns: transcript -> reply
 1. Ich wohne seit drei Jahren in Berlin. -> Schön, dass du in Berlin bist! Ich lebe seit zwei Jahren hier und finde die Stadt sehr interessant. Magst du Berlin?
 2. Am Wochenende fahre ich oft mit dem Fahrrad an der Spree  entlang. -> Das klingt schön! Ich fahre manchmal auch mit dem Fahrrad entlang der Spree – besonders an sonnigen Tagen. Magst du das Wetter am Wochenende?
 3. Was machst du eigentlich in deiner Freizeit, wenn du nicht  arbeitest? -> In meiner Freizeit mache ich gern Sport – ich gehe zum Beispiel Bouldern oder laufe im Park. Manchmal koche ich auch gerne. Und du? Hast du bestimmte Hobbys?
 4. Meine Lieblingsstadt in Deutschland ist Hamburg, weil sie  direkt am Wasser liegt. -> Hamburg ist wirklich eine schöne Stadt – ich mag besonders die Altstadt und das Hafenamt. Hast du schon mal einen Ausflug nach Hamburg gemacht?
 5. Ich habe letzte Woche einen Deutschkurs angefangen, der mir  sehr gut gefällt. -> Das ist toll! Ich mache gerade auch einen Deutschkurs – an der Volkshochschule. Wie findest du den? Ist er schwer oder eher einfach?
 6. Wenn ich am Abend nach Hause komme, koche ich meistens  etwas Einfaches und höre dabei Musik. -> Das klingt gemütlich! Ich mache oft dasselbe – etwas Einfaches kochen und dabei einen Podcast hören. Welche Musik magst du am liebsten?
 7. Kannst du mir vielleicht ein paar Tipps geben, wie ich  meinen Wortschatz besser erweitern kann? -> Natürlich! Ein guter Tipp ist, viel zu lesen – zum Beispiel Zeitungen, Bücher oder sogar Kurznachrichten. Du kannst auch versuchen, neue Wörter in deinen Alltag zu integrieren, zum Beispiel beim Kochen oder bei Gesprächen. Hast du schon mal versucht, einen Sprachpartner zu finden?
 8. Obwohl das Wetter am Sonntag ziemlich schlecht war, sind  wir mit Freunden in den Park gegangen und haben dort ein  Picknick gemacht. -> Das klingt trotzdem sehr nett! Manchmal ist es doch schön, mal im Freien zu sein, auch wenn das Wetter nicht perfekt ist. War das Picknick trotzdem lustig?
 9. Ich interessiere mich sehr für Geschichte und würde deshalb  gern einmal nach Dresden fahren, um die alten Gebäude und  Museen zu besichtigen. -> Das klingt sehr interessant! Dresden hat wirklich viele schöne alte Gebäude und beeindruckende Museen. Hast du schon mal eine Reise in den Südosten Deutschlands gemacht?
10. In meiner Heimastadt gibt es einen großen Markt, auf dem  man frische Produkte kaufen kann und am Wochenende treffen  sich dort viele Menschen, um miteinander zu sprechen oder  etwas zu essen. -> Das klingt sehr lebhaft! In Berlin gibt es auch viele schöne Märkte – besonders an den Wochenenden. Gehst du oft auf Märkte?

(e) GPU: start 61 °C, end 67 °C
```

### Warm bench — run B (`--runs 1`)

```text
(a) Server metrics (n=10)
metric                       p50       p90       max
----------------------------------------------------
audio_s                     4.67      7.68      9.91
stt_ms                       500       720       796
llm_first_token_ms           611       848       934
first_sentence_ms           1315      1995      2005
tts_first_ms                 541      1379      1568
first_audio_ms              1840      3168      3575
total_ms                    3754      4623      5064
sentences                      3         3         4

(b) Derived stages (ms)
stage                        p50       p90
------------------------------------------
stt                          500       720
llm_to_first_token           116       135
first_sentence_wait          524      1183
tts_first                    541      1379

(c) Estimated end-of-speech -> first audio (first_audio_ms + 768 ms VAD tail)
    p50: 2608 ms    p90: 3936 ms    target: 1500 ms
    vs target: p50 +1108 ms    p90 +2436 ms

(d) Turns: transcript -> reply
 1. Ich wohne seit drei Jahren in Berlin. -> Schön, dass du hier bist! Berlin ist eine tolle Stadt, aber nicht immer leicht zu finden. Wie bist du hierher gekommen? Aus welchem Land?
 2. Am Wochenende fahre ich oft mit dem Fahrrad an der Spree  entlang. -> Das klingt schön! Ich fahre manchmal auch mit dem Fahrrad entlang der Spree, besonders am Wochenende. Magst du die Ruhe dort oder die Aussicht?
 3. Was machst du eigentlich in deiner Freizeit, wenn du nicht  arbeitest? -> In meiner Freizeit mache ich gerne Sport, zum Beispiel Bouldern oder Yoga. Ich esse auch gern selbstgemachte Pizza und höre oft Podcasts. Was machst du in deiner Freizeit?
 4. Meine Lieblingsstadt in Deutschland ist Hamburg, weil sie  direkt am Wasser liegt. -> Hamburg ist wirklich eine schöne Stadt – ich mag besonders den Hafen und die Altstadt. Hast du schon mal einen Ausflug zum Elbtunnel oder aufs Jungfernstieg gemacht?
 5. Ich habe letzte Woche einen Deutschkurs angefangen, der mir  sehr gut gefällt. -> Das ist großartig! Ich mache auch gerade einen Deutschkurs, und es ist echt hilfreich. Wie findest du die anderen Teilnehmer?
 6. Wenn ich am Abend nach Hause komme, koche ich meistens  etwas Einfaches und höre dabei Musik. -> Das klingt sehr entspannt! Ich koche oft auch etwas Einfaches, besonders nach einem langen Tag. Hast du einen Lieblingskochkanal auf YouTube?
 7. Kannst du mir vielleicht ein paar Tipps geben, wie ich  meinen Wortschatz besser erweitern kann? -> Natürlich! Ein guter Tipp ist, viel zu lesen – zum Beispiel Bücher, Nachrichten oder Blogs. Du kannst auch versuchen, neue Wörter in dein Tagebuch zu schreiben und sie im Gespräch zu verwenden. Hast du schon mal mit einem Sprachpartner geübt?
 8. Obwohl das Wetter am Sonntag ziemlich schlecht war, sind  wir mit Freunden in den Park gegangen und haben dort ein  Picknick gemacht. -> Das ist sehr mutig! Es ist schön, dass ihr trotz des Wetters Spaß hattet. Habt ihr euch gut amüsiert, oder war es doch etwas schwierig?
 9. Ich interessiere mich sehr für Geschichte und würde deshalb  gern einmal nach Dresden fahren, um die alten Gebäude und  Museen zu besichtigen. -> Dresden ist eine wundervolle Stadt mit einer unglaublichen Architektur! Die Altstadt und das Zwinger sind besonders sehenswert. Hast du schon mal einen Ausflug ins Erzgebirge gemacht?
10. In meiner Heimatstadt gibt es einen großen Markt, auf dem  man frische Produkte kaufen kann  und am Wochenende treffen sich dort viele Menschen, um  miteinander zu sprechen oder etwas zu essen. -> Das klingt sehr gemütlich! In Berlin gibt es auch viele Märkte, besonders in den Bezirken wie Neukölln oder Mitte. Gehst du oft auf Märkte?

(e) GPU: start 65 °C, end 68 °C
```

## Review (Claude Code fills this in)
- **Verdict:** accept (2026-11-05)
- **Notes:**
  - Diff limited to allowed files. `make test` (30) and `make lint` are clean. The warm-up isn't awaited in `start()` and is cancelled in `close()`; failures are logged and swallowed.
  - Lead re-verified the cold start: `qwen3:14b` was unloaded (not in `/api/ps`); on 8771 with `--first-delay 6`, turn 1 had `llm_first_token_ms` 455 and `first_audio_ms` 1379 (T001 cold: 7400 / 8781). Afterwards `ollama ps` showed the normal "9 minutes from now".
  - The warm-up ends on an assistant message, so Ollama treats it as a continuation. The cached prefix then covers system prompt + opener for the first real turn.
  - Kilo's note stands: within one session `qwen3:14b` repeats its earlier answer when the learner repeats a sentence verbatim, regardless of seed. That's model behavior, not a seed bug; it's for T010.
