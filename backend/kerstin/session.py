"""One conversation between the learner and Kerstin.

Turn flow (see docs/ARCHITECTURE.md):
  learner audio -> STT -> history -> LLM stream -> sentence splitter -> TTS -> client

LLM generation and TTS run concurrently: as soon as the first sentence is
complete it is synthesized and sent while the LLM keeps generating.
A new utterance or an explicit "interrupt" cancels the running turn (barge-in).
"""

from __future__ import annotations

import asyncio
import logging
import struct
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from . import score as scoring
from .audio import pcm16_duration_s, pcm16_rms_dbfs
from .exam import MODERATION_PREFIX, ExamPart, ExamPlan, is_moderation
from .feedback_checks import parse_errors
from .llm import Message, OllamaLLM
from .mistakes import CATEGORIES, MistakeLog, classify
from .prompts import PromptStore
from .stt import STT
from .stt_filter import clean_transcript, is_echo
from .text import SentenceSplitter, clean_for_tts, strip_think
from .thermal import ThermalGuard, ThermalStatus
from .tts import TTS

log = logging.getLogger(__name__)

SendJson = Callable[[dict], Awaitable[None]]
SendBytes = Callable[[bytes], Awaitable[None]]

MIN_UTTERANCE_S = 0.35


def format_feedback_transcript(history: list[Message]) -> str:
    lines = []
    for message in history:
        if is_moderation(message):
            lines.append(f"--- {message['content'][len(MODERATION_PREFIX):]} ---")
        else:
            speaker = "Lernende Person" if message["role"] == "user" else "Kerstin"
            lines.append(f"{speaker}: {message['content']}")
    return "\n".join(lines)


@dataclass
class Deps:
    stt: STT
    llm: OllamaLLM
    tts: TTS
    prompts: PromptStore
    history_max_turns: int = 24
    llm_warmup: bool = True
    first_clause_min_words: int = 4
    stt_min_rms_dbfs: float = -55.0
    stt_filter: bool = True
    feedback_lang: str = "en"
    ollama_model: str = "gemma4:26b"
    feedback_model: str | None = None
    feedback_temperature: float = 0.3
    score_seed: int = 7
    ollama_max_loaded: int = 2
    hint_temperature: float = 0.2
    mistakes: MistakeLog | None = None
    thermal: ThermalGuard | None = None


@dataclass
class TurnMetrics:
    audio_s: float = 0.0
    audio_dbfs: float = 0.0
    stt_ms: int = 0
    llm_first_token_ms: int = 0
    first_sentence_ms: int = 0  # t0 until the consumer got the first non-empty sentence
    tts_first_ms: int = 0  # duration of the first sentence's synthesize() call
    first_audio_ms: int = 0  # from end of learner speech (server receive) to first audio sent
    total_ms: int = 0
    sentences: int = 0


def exam_enter_marker(part: ExamPart, index: int) -> str | None:
    if part.kind == "kerstin_talk":
        return (
            f"Teil {index + 1} – {part.title}: Halte jetzt deinen Vortrag. "
            "Du sprichst zu einer einzigen Person, deiner Gesprächspartnerin – "
            "sag ‚du‘, nie ‚ihr/euch‘."
        )
    if part.kind == "dialog":
        if "plan" in part.title.lower():
            return (
                f"Teil {index + 1} – {part.title}: Eröffne den Teil mit einem "
                "ersten konkreten Vorschlag (z. B. ‚Ich schlage vor, …‘)."
            )
        return (
            f"Teil {index + 1} – {part.title}: Eröffne den Teil mit einer "
            "klaren eigenen Position."
        )
    return None


@dataclass
class Session:
    deps: Deps
    send_json: SendJson
    send_bytes: SendBytes
    scenario_key: str
    focus: list[str] = field(default_factory=list)
    exam: ExamPlan | None = None
    part_index: int = 0
    history: list[Message] = field(default_factory=list)
    turn_id: int = 0
    _system: str | None = None
    _collect_followup_done: bool = False
    _pending_metrics: tuple[TurnMetrics, float] | None = None
    _turn_task: asyncio.Task | None = None
    _warmup_task: asyncio.Task | None = None
    _hint_task: asyncio.Task | None = None

    # ---------- public API (called by the websocket handler) ----------

    async def start(self) -> None:
        sc = self.deps.prompts.scenario(self.scenario_key)
        if self.exam is not None:
            self.focus = []
            self._system = self.deps.prompts.exam_system_prompt(self.exam)
        else:
            self._system = self.deps.prompts.system_prompt(
                self.scenario_key, self.focus or None
            )
        self.history.clear()
        session_message = {
            "type": "session",
            "scenario": sc.key,
            "title": sc.title,
            "focus": [CATEGORIES[key] for key in self.focus],
        }
        if self.exam is not None:
            session_message["exam"] = {
                "preset": self.exam.preset,
                "title": self.exam.title,
                "note": self.exam.note,
                "parts": [
                    {
                        "kind": part.kind,
                        "title": part.title,
                        "seconds": part.seconds,
                    }
                    for part in self.exam.parts
                ],
            }
        await self.send_json(session_message)

        thermal = await self._thermal_check()
        if thermal is not None and thermal.state == "hot":
            await self._send_thermal(thermal)
            log.info("session start thermal hot (gpu=%g °C)", thermal.temp_c)
            return

        greeting = self.exam.greeting if self.exam is not None else sc.opener
        if self.deps.llm_warmup:
            system = {"role": "system", "content": self._system}
            warmup_messages = [system, {"role": "assistant", "content": greeting}]
            self._warmup_task = asyncio.create_task(self.deps.llm.warmup(warmup_messages))
        await self._speak_fixed(greeting)
        if self.exam is not None:
            await self._enter_part(0)

    async def handle_audio(self, pcm16: bytes) -> None:
        await self.interrupt()
        self.turn_id += 1
        self._turn_task = asyncio.create_task(self._turn(self.turn_id, pcm16))

    async def interrupt(self) -> None:
        task = self._turn_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._turn_task = None

    async def hint(self, query: str) -> None:
        query = query.strip()
        if not query:
            return

        task = self._hint_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._hint_task = None

        if len(query) > 120:
            await self.send_json(
                {"type": "hint", "query": query[:120], "error": "too_long"}
            )
            return

        thermal = await self._thermal_check()
        if thermal is not None and thermal.state == "hot":
            await self.send_json(
                {
                    "type": "hint",
                    "query": query,
                    "error": "thermal",
                    "temp_c": thermal.temp_c,
                }
            )
            log.info("hint thermal hot (gpu=%g °C)", thermal.temp_c)
            return

        self._hint_task = asyncio.create_task(self._hint(query))

    async def feedback(self, lang: str | None = None, save_mistakes: bool = False) -> None:
        await self.interrupt()

        if lang not in (None, "en", "de"):
            log.info("feedback language %r invalid; using %r", lang, self.deps.feedback_lang)
            lang = None
        lang = lang or self.deps.feedback_lang

        thermal = await self._thermal_check()
        if thermal is not None and thermal.state == "hot":
            await self._send_thermal(thermal)
            log.info("feedback thermal hot (gpu=%g °C)", thermal.temp_c)
            return

        learner_lines = [
            m
            for m in self.history
            if m["role"] == "user" and not is_moderation(m)
        ]
        if not learner_lines:
            await self.send_json({"type": "feedback", "markdown": "_Noch keine Äußerungen._"})
            return
        transcript = format_feedback_transcript(self.history)
        await self.send_json({"type": "status", "state": "feedback_running"})
        prompt = self.deps.prompts.feedback_prompt(transcript, lang)

        model, keep_alive = await self._feedback_model_choice()

        started = time.perf_counter()
        text = await self.deps.llm.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=1200,
            temperature=self.deps.feedback_temperature,
            model=model,
            keep_alive=keep_alive,
        )
        markdown = strip_think(text).strip()
        await self.send_json({"type": "feedback", "markdown": markdown})
        log.info(
            "feedback ok (model=%s ms=%d)",
            model,
            int((time.perf_counter() - started) * 1000),
        )

        if self.exam is not None:
            await self._score_exam(lang)

        if save_mistakes and self.deps.mistakes is not None:
            categories = [classify(error) for error in parse_errors(markdown)]
            try:
                count = await self.deps.mistakes.record(
                    self.scenario_key, lang, categories
                )
            except Exception as exc:  # noqa: BLE001 — feedback already sent
                log.warning("mistakes save failed (%s)", type(exc).__name__)
                await self.send_json(
                    {"type": "mistakes_saved", "count": 0, "error": "failed"}
                )
            else:
                log.info("mistakes saved (n=%d)", count)
                await self.send_json({"type": "mistakes_saved", "count": count})

    async def _feedback_model_choice(self) -> tuple[str, str | None]:
        chat_model = self.deps.ollama_model
        model = self.deps.feedback_model or chat_model
        keep_alive: str | None = None
        if model != chat_model:
            try:
                loaded = await self.deps.llm.loaded_models()
            except Exception as exc:  # noqa: BLE001 — fail safe, not fail open
                log.info("feedback model fallback (ps failed: %s)", type(exc).__name__)
                model = chat_model
            else:
                others = [name for name in loaded if name not in (chat_model, model)]
                if len(others) + 1 > self.deps.ollama_max_loaded:
                    log.info("feedback model fallback (slots busy)")
                    model = chat_model
                else:
                    if (
                        chat_model in loaded
                        and len(others) + 2 > self.deps.ollama_max_loaded
                    ):
                        await self.deps.llm.unload(chat_model)
                    keep_alive = "0"
        return model, keep_alive

    async def _score_exam(self, lang: str) -> None:
        if self.exam is None:
            return
        learner = scoring.learner_text(self.history)
        if len(learner.split()) < 60:
            await self.send_json(
                {"type": "exam_score", "error": "zu wenig Material für eine Einschätzung"}
            )
            log.info("exam score skipped: too little material")
            return

        thermal = await self._thermal_check()
        if thermal is not None and thermal.state == "hot":
            await self.send_json(
                {
                    "type": "exam_score",
                    "error": "GPU zu warm – Einschätzung gerade nicht möglich",
                    "temp_c": thermal.temp_c,
                }
            )
            log.info("exam score thermal hot (gpu=%g °C)", thermal.temp_c)
            return

        await self.send_json({"type": "status", "state": "score_running"})
        started = time.perf_counter()
        model, keep_alive = await self._feedback_model_choice()
        prompt = scoring.score_prompt(self.deps.prompts, self.history, self.exam, lang)
        parsed = None
        for attempt in (1, 2):
            try:
                raw = await self.deps.llm.chat(
                    [{"role": "user", "content": prompt}],
                    max_tokens=700,
                    temperature=0.0,
                    model=model,
                    keep_alive=keep_alive,
                    fmt="json",
                    seed=self.deps.score_seed,
                )
            except Exception as exc:  # noqa: BLE001 — scoring must not break feedback
                log.info("exam score failed (%s)", type(exc).__name__)
                break
            parsed = scoring.parse_score(strip_think(raw).strip(), learner)
            if parsed is not None:
                break
            log.info("exam score parse failed (attempt=%d)", attempt)

        if parsed is None:
            await self.send_json(
                {"type": "exam_score", "error": "Einschätzung konnte nicht erstellt werden"}
            )
            return

        await self.send_json(
            {
                "type": "exam_score",
                "criteria": [
                    {
                        "key": criterion.key,
                        "label": criterion.label,
                        "band": criterion.band,
                        "band_label": criterion.band_label,
                        "reason": criterion.reason,
                        "evidence": criterion.evidence,
                    }
                    for criterion in parsed.criteria
                ],
                "overall_band": parsed.overall_band,
                "overall_label": parsed.overall_label,
                "error_density": parsed.error_density,
                "grammar_errors": parsed.grammar_errors,
                "note": scoring.SCORE_NOTE,
            }
        )
        log.info(
            "exam score ok (model=%s ms=%d dropped_evidence=%d)",
            model,
            int((time.perf_counter() - started) * 1000),
            parsed.dropped_evidence,
        )

    async def close(self) -> None:
        hint_task = self._hint_task
        if hint_task and not hint_task.done():
            hint_task.cancel()
            try:
                await hint_task
            except asyncio.CancelledError:
                pass
        self._hint_task = None

        task = self._warmup_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._warmup_task = None
        await self.interrupt()

    # ---------- internals ----------

    def _messages(self) -> list[Message]:
        system = {
            "role": "system",
            "content": self._system
            or (
                self.deps.prompts.exam_system_prompt(self.exam)
                if self.exam is not None
                else self.deps.prompts.system_prompt(
                    self.scenario_key, self.focus or None
                )
            ),
        }
        recent = self.history[-self.deps.history_max_turns :]
        markers = [message for message in self.history if is_moderation(message)]
        if markers and markers[-1] not in recent:
            recent = [markers[-1], *recent]
        return [system, *recent]

    async def _thermal_check(self) -> ThermalStatus | None:
        if self.deps.thermal is None:
            return None
        return await self.deps.thermal.check()

    async def _send_thermal(self, status: ThermalStatus, turn_id: int | None = None) -> None:
        message = {"type": "thermal", "state": status.state, "temp_c": status.temp_c}
        if turn_id is not None:
            message["turn"] = turn_id
        await self.send_json(message)

    async def _hint(self, query: str) -> None:
        started = time.perf_counter()
        context = format_feedback_transcript(
            [m for m in self.history[-4:] if not is_moderation(m)]
        )
        try:
            prompt = self.deps.prompts.hint_prompt(query, context)
            text = await self.deps.llm.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=120,
                temperature=self.deps.hint_temperature,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — any hint failure becomes a short UI error
            await self.send_json({"type": "hint", "query": query, "error": "failed"})
            log.info("hint failed (%s)", type(exc).__name__)
            return

        await self.send_json(
            {"type": "hint", "query": query, "markdown": strip_think(text).strip()}
        )
        log.info("hint ok (ms=%d)", int((time.perf_counter() - started) * 1000))

    async def _send_audio(self, turn_id: int, wav: bytes | None) -> None:
        if wav:
            # 4-byte big-endian turn id header lets the client drop stale audio after barge-in
            await self.send_bytes(struct.pack(">I", turn_id) + wav)

    async def _speak_fixed(self, text: str) -> None:
        self.history.append({"role": "assistant", "content": text})
        await self.send_json({"type": "reply_text", "turn": self.turn_id, "text": text})
        await self._send_audio(self.turn_id, await self.deps.tts.synthesize(clean_for_tts(text)))
        await self.send_json({"type": "reply_done", "turn": self.turn_id})

    async def _turn(self, turn_id: int, pcm16: bytes) -> None:
        m = TurnMetrics(
            audio_s=round(pcm16_duration_s(pcm16), 2),
            audio_dbfs=round(pcm16_rms_dbfs(pcm16), 1),
        )
        t0 = time.perf_counter()

        def ms() -> int:
            return int((time.perf_counter() - t0) * 1000)

        if m.audio_s < MIN_UTTERANCE_S:
            await self.send_json(
                {"type": "stt_empty", "turn": turn_id, "reason": "too_short"}
            )
            log.info("turn %s dropped: too_short (audio_dbfs=%s)", turn_id, m.audio_dbfs)
            return

        if m.audio_dbfs < self.deps.stt_min_rms_dbfs:
            await self.send_json(
                {"type": "stt_empty", "turn": turn_id, "reason": "too_quiet"}
            )
            log.info("turn %s dropped: too_quiet (audio_dbfs=%s)", turn_id, m.audio_dbfs)
            return

        thermal = await self._thermal_check()
        if thermal is not None and thermal.state == "hot":
            await self._send_thermal(thermal, turn_id)
            log.info("turn %s thermal hot (gpu=%g °C)", turn_id, thermal.temp_c)
            return

        if (
            self.exam is not None
            and self.part_index < len(self.exam.parts)
            and self.exam.parts[self.part_index].kind == "prep"
        ):
            await self.send_json(
                {"type": "stt_empty", "turn": turn_id, "reason": "prep"}
            )
            log.info("turn %s dropped: prep", turn_id)
            return

        await self.send_json({"type": "status", "state": "transcribing", "turn": turn_id})
        text = await self.deps.stt.transcribe(pcm16)
        m.stt_ms = ms()

        if self.deps.stt_filter:
            text, reason = clean_transcript(text)
            if not text:
                reason = reason or "empty"
                await self.send_json(
                    {"type": "stt_empty", "turn": turn_id, "reason": reason}
                )
                log.info("turn %s dropped: %s (audio_dbfs=%s)", turn_id, reason, m.audio_dbfs)
                return
            if reason:
                log.info("turn %s %s (audio_dbfs=%s)", turn_id, reason, m.audio_dbfs)

            last_reply = next(
                (
                    message["content"]
                    for message in reversed(self.history)
                    if message["role"] == "assistant"
                ),
                "",
            )
            if is_echo(text, last_reply):
                await self.send_json(
                    {"type": "stt_empty", "turn": turn_id, "reason": "echo"}
                )
                log.info("turn %s dropped: echo (audio_dbfs=%s)", turn_id, m.audio_dbfs)
                return

        if not text:
            await self.send_json(
                {"type": "stt_empty", "turn": turn_id, "reason": "empty"}
            )
            log.info("turn %s dropped: empty (audio_dbfs=%s)", turn_id, m.audio_dbfs)
            return

        await self.send_json({"type": "transcript", "turn": turn_id, "text": text})
        self.history.append({"role": "user", "content": text})

        if self._collecting():
            await self.send_json({"type": "collected", "turn": turn_id})
            return

        self._pending_metrics = (m, t0)
        try:
            await self._respond(turn_id)
        finally:
            self._pending_metrics = None

    async def _respond(self, turn_id: int, max_tokens: int | None = None) -> None:
        pending = self._pending_metrics
        self._pending_metrics = None
        if pending is None:
            m = TurnMetrics()
            t0 = time.perf_counter()
        else:
            m, t0 = pending

        def ms() -> int:
            return int((time.perf_counter() - t0) * 1000)

        queue: asyncio.Queue[str | None] = asyncio.Queue()
        spoken: list[str] = []

        async def produce() -> None:
            splitter = SentenceSplitter(
                first_clause_min_words=self.deps.first_clause_min_words
            )
            first = True
            try:
                async for piece in self.deps.llm.stream_chat(
                    self._messages(), max_tokens=max_tokens
                ):
                    if first:
                        m.llm_first_token_ms = ms()
                        first = False
                    for sent in splitter.feed(piece):
                        await queue.put(sent)
                for sent in splitter.flush():
                    await queue.put(sent)
            finally:
                await queue.put(None)

        async def consume() -> None:
            first_sentence = True
            first_tts = True
            while (sent := await queue.get()) is not None:
                sent = strip_think(sent).strip()
                if not sent:
                    continue
                if first_sentence:
                    m.first_sentence_ms = ms()
                    first_sentence = False
                await self.send_json({"type": "reply_text", "turn": turn_id, "text": sent})
                if first_tts:
                    synth_started = time.perf_counter()
                    wav = await self.deps.tts.synthesize(clean_for_tts(sent))
                    m.tts_first_ms = int((time.perf_counter() - synth_started) * 1000)
                    first_tts = False
                else:
                    wav = await self.deps.tts.synthesize(clean_for_tts(sent))
                await self._send_audio(turn_id, wav)
                if not m.first_audio_ms:
                    m.first_audio_ms = ms()
                spoken.append(sent)
                m.sentences += 1

        await self.send_json({"type": "status", "state": "thinking", "turn": turn_id})
        producer = asyncio.create_task(produce())
        try:
            await consume()
            await producer
            m.total_ms = ms()
            await self.send_json({"type": "reply_done", "turn": turn_id})
            await self.send_json({"type": "metrics", "turn": turn_id, **m.__dict__})
            log.info("turn %s metrics %s", turn_id, m.__dict__)
        except asyncio.CancelledError:
            producer.cancel()
            await self.send_json({"type": "reply_interrupted", "turn": turn_id})
            raise
        except Exception as e:
            producer.cancel()
            log.exception("turn %s failed", turn_id)
            await self.send_json({"type": "error", "turn": turn_id, "message": str(e)})
        finally:
            if spoken:
                self.history.append({"role": "assistant", "content": " ".join(spoken)})

    async def _kerstin_says(self, marker: str, max_tokens: int | None = None) -> None:
        self.turn_id += 1
        self.history.append(
            {"role": "user", "content": f"{MODERATION_PREFIX}{marker}"}
        )
        thermal = await self._thermal_check()
        if thermal is not None and thermal.state == "hot":
            await self._send_thermal(thermal, self.turn_id)
            log.info("kerstin_says thermal hot (gpu=%g °C)", thermal.temp_c)
            return
        await self._respond(self.turn_id, max_tokens=max_tokens)

    def _collecting(self) -> bool:
        if self.exam is None or self.part_index >= len(self.exam.parts):
            return False
        part = self.exam.parts[self.part_index]
        return part.kind == "learner_talk" and not self._collect_followup_done

    async def _enter_part(self, index: int) -> None:
        if self.exam is None:
            return
        self.part_index = index
        self._collect_followup_done = False
        part = self.exam.parts[index]
        card = part.card
        if part.kind == "kerstin_talk" and card:
            card = {"title": card.get("title")}
        await self.send_json(
            {
                "type": "exam_part",
                "index": index,
                "kind": part.kind,
                "title": part.title,
                "seconds": part.seconds,
                "ui_text": part.ui_text,
                "card": card,
            }
        )
        log.info("exam part %s %s", index, part.kind)
        marker = exam_enter_marker(part, index)
        if marker is not None:
            await self._kerstin_says(
                marker,
                max_tokens=450 if part.kind == "kerstin_talk" else None,
            )

    async def exam_next(self) -> None:
        if self.exam is None:
            await self.send_json(
                {"type": "error", "message": "exam_next outside exam mode"}
            )
            return
        await self.interrupt()
        if self.part_index >= len(self.exam.parts):
            return
        part = self.exam.parts[self.part_index]
        if part.kind == "learner_talk" and not self._collect_followup_done:
            self._collect_followup_done = True
            await self._kerstin_says(
                f"Teil {self.part_index + 1} – Rückfrage zu deinem Vortrag: "
                "Stelle genau eine kurze Frage."
            )
            return
        if self.part_index + 1 >= len(self.exam.parts):
            await self.send_json({"type": "exam_part", "kind": "done"})
            log.info("exam done")
            return
        await self._enter_part(self.part_index + 1)
