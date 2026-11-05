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

from .audio import pcm16_duration_s, pcm16_rms_dbfs
from .llm import Message, OllamaLLM
from .prompts import PromptStore
from .stt import STT
from .stt_filter import clean_transcript, is_echo
from .text import SentenceSplitter, clean_for_tts, strip_think
from .tts import TTS

log = logging.getLogger(__name__)

SendJson = Callable[[dict], Awaitable[None]]
SendBytes = Callable[[bytes], Awaitable[None]]

MIN_UTTERANCE_S = 0.35


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


@dataclass
class Session:
    deps: Deps
    send_json: SendJson
    send_bytes: SendBytes
    scenario_key: str
    history: list[Message] = field(default_factory=list)
    turn_id: int = 0
    _turn_task: asyncio.Task | None = None
    _warmup_task: asyncio.Task | None = None

    # ---------- public API (called by the websocket handler) ----------

    async def start(self) -> None:
        sc = self.deps.prompts.scenario(self.scenario_key)
        self.history.clear()
        await self.send_json({"type": "session", "scenario": sc.key, "title": sc.title})
        if self.deps.llm_warmup:
            system = {
                "role": "system",
                "content": self.deps.prompts.system_prompt(self.scenario_key),
            }
            warmup_messages = [system, {"role": "assistant", "content": sc.opener}]
            self._warmup_task = asyncio.create_task(self.deps.llm.warmup(warmup_messages))
        await self._speak_fixed(sc.opener)

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

    async def feedback(self) -> None:
        await self.interrupt()
        learner_lines = [m for m in self.history if m["role"] == "user"]
        if not learner_lines:
            await self.send_json({"type": "feedback", "markdown": "_Noch keine Äußerungen._"})
            return
        transcript = "\n".join(
            f"{'Lernende Person' if m['role'] == 'user' else 'Kerstin'}: {m['content']}"
            for m in self.history
        )
        await self.send_json({"type": "status", "state": "feedback_running"})
        prompt = self.deps.prompts.feedback_prompt(transcript)
        text = await self.deps.llm.chat([{"role": "user", "content": prompt}], max_tokens=1200)
        await self.send_json({"type": "feedback", "markdown": strip_think(text).strip()})

    async def close(self) -> None:
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
        system = {"role": "system", "content": self.deps.prompts.system_prompt(self.scenario_key)}
        return [system, *self.history[-self.deps.history_max_turns :]]

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
                (m["content"] for m in reversed(self.history) if m["role"] == "assistant"),
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

        queue: asyncio.Queue[str | None] = asyncio.Queue()
        spoken: list[str] = []

        async def produce() -> None:
            splitter = SentenceSplitter(
                first_clause_min_words=self.deps.first_clause_min_words
            )
            first = True
            try:
                async for piece in self.deps.llm.stream_chat(self._messages()):
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
