# WebSocket protocol — `/ws`

Version 0.1. Text frames are JSON; binary frames are audio. Any change here must be made in the same commit as the code change on both sides.

## Client → server

| Frame | Meaning |
|---|---|
| `{"type":"start","scenario":"<key>","use_focus"?,"exam"?:"<preset key>","exam_seed"?}` | Start (or restart) a session. Keys from `GET /api/scenarios`. `use_focus` is opt-in, strict boolean, and defaults to off. `exam` selects an exam preset; `exam_seed` is for the eval/tests only. An unknown preset returns `error`. |
| **binary** | One complete learner utterance: 16 kHz, mono, signed 16-bit little-endian PCM, no header. Implicitly starts turn `n+1` and cancels any running turn. |
| `{"type":"interrupt"}` | Learner barged in; cancel the running turn. |
| `{"type":"hint","query"}` | Typed word/phrase lookup; text only, outside the conversation. |
| `{"type":"end","feedback_lang"?:"en"\|"de","save_mistakes"?}` | End the conversation and request feedback. Invalid values use the server default. `save_mistakes` is opt-in and defaults to `false`. |
| `{"type":"exam_next"}` | In exam mode: finish or advance the current part. Outside exam mode it returns `error`. |
| `{"type":"ping"}` | Keepalive → `pong`. |

## Server → client

| Frame | Meaning |
|---|---|
| `{"type":"session","scenario","title","focus":[...],"exam"?}` | Session started; reset UI, `turn = 0`. `focus` is the list of active focus labels, empty when off. `exam` has `{preset,title,note,parts:[{kind,title,seconds}]}` when exam mode is active. |
| `{"type":"status","state":"transcribing"\|"thinking"\|"feedback_running"\|"score_running","turn"}` | Progress hints. |
| `{"type":"transcript","turn","text"}` | What STT heard. |
| `{"type":"collected","turn"}` | Exam collect mode: the utterance was stored and no LLM call was made. |
| `{"type":"exam_part","index"?, "kind","title"?,"seconds"?,"ui_text"?,"card"?}` | Exam part entered. `card` is the learner's card for `prep`/`learner_talk`/`dialog`, Kerstin's card title only for `kerstin_talk`, or `null`; `kind:"done"` has no index/card. |
| `{"type":"stt_empty","turn","reason"?}` | Nothing recognized. Optional `reason`: `too_short`, `too_quiet`, `prep`, `tags_only`, `hallucination`, `echo` or `empty`. |
| `{"type":"thermal","state":"hot","temp_c","turn"?}` | GPU too hot; no new STT/LLM work. `turn` is absent for `start`/`feedback`. |
| `{"type":"reply_text","turn","text"}` | One sentence of Kerstin's reply (sent just before its audio). Turn 0 = opener. |
| **binary** | `[4-byte big-endian uint32 turn id][WAV file]` — one sentence of audio. Drop if turn id < current turn. |
| `{"type":"reply_done","turn"}` | Reply finished. |
| `{"type":"reply_interrupted","turn"}` | Reply cancelled by barge-in. |
| `{"type":"metrics","turn","audio_s","audio_dbfs","stt_ms","llm_first_token_ms","first_sentence_ms","tts_first_ms","first_audio_ms","total_ms","sentences"}` | Timings (ms measured from server receiving the utterance). `audio_dbfs` = input RMS level (dBFS, one decimal). `first_sentence_ms` = first spoken chunk (early clause or sentence) available to the consumer; `tts_first_ms` = duration of that first chunk's TTS call. |
| `{"type":"feedback","markdown"}` | End-of-session report. |
| `{"type":"exam_score","criteria":[{"key","label","band","band_label","reason","evidence"}],"overall_band","overall_label","note"}` | Exam-only transcript estimate after `feedback`. Bands 1–4; evidence is a verbatim learner quote or `null`. Errors: `{"type":"exam_score","error"}`. |
| `{"type":"mistakes_saved","count","error"?:"failed"}` | Optional feedback follow-up when the learner opted in. `count` is the number of category rows stored; an error does not affect the feedback. |
| `{"type":"hint","query","markdown"}` or `{"type":"hint","query","error":"too_long"\|"thermal"\|"failed","temp_c"?}` | Hint answer or short error. No `turn`; never affects turn state, history or feedback. |
| `{"type":"error","message","turn"?}` | Error. |
| `{"type":"pong"}` | Reply to ping. |

## Turn ids
Both sides start at 0 after `session`. Each binary utterance from the client increments the turn on both sides (the server increments even if the utterance is too short and ignored, to stay in sync). In exam mode, server-initiated Kerstin turns (her talk, part openers and follow-up) also increment the server turn id.

## HTTP
- `GET /health` → Ollama reachability, model presence, configured backends, `gpu_temp_c` (number or null) and `thermal` (`ok|hot|unknown|disabled`).
- `GET /api/scenarios` → `[{"key","title"}]`.
- `GET /api/exams` → `[{"key","title","note"}]` from the exam presets; `[]` if the exam file cannot be loaded.
- `GET /api/mistakes` → `{"enabled": bool, "sessions": n, "categories": [{"key","label","count"}]}`. The summary covers the last 90 days; a missing database reads as zeros and is not created.
- `DELETE /api/mistakes` → `{"cleared": true}`; returns 404 when the log is disabled.
- `GET /` → browser client.
