"""Text-to-speech backends. Each returns a complete WAV file (bytes) per sentence."""

from __future__ import annotations

import asyncio
import inspect
import io
import logging
import time
import wave
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import TYPE_CHECKING, Protocol

import httpx

from .config import Settings
from .voices import VoiceInfo, resolve_voice

if TYPE_CHECKING:
    from .session import Deps

log = logging.getLogger(__name__)


class TTS(Protocol):
    async def synthesize(self, text: str) -> bytes | None: ...


class NoTTS:
    async def synthesize(self, text: str) -> bytes | None:
        return None


class PiperTTS:
    """Local Piper voice. Default: de_DE-thorsten-medium (download via `make voice`)."""

    def __init__(self, s: Settings) -> None:
        from piper import PiperVoice  # lazy import

        if not s.piper_voice_path.exists():
            raise FileNotFoundError(
                f"Piper voice not found at {s.piper_voice_path}. Run `make voice`."
            )
        log.info("Loading Piper voice %s", s.piper_voice_path.name)
        self.voice = PiperVoice.load(str(s.piper_voice_path))
        self.length_scale = s.piper_length_scale

    def _run(self, text: str) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            # piper1-gpl (>=1.3) uses synthesize_wav; older piper-tts uses synthesize
            if hasattr(self.voice, "synthesize_wav"):
                try:
                    from piper import SynthesisConfig

                    cfg = SynthesisConfig(length_scale=self.length_scale)
                    self.voice.synthesize_wav(text, wav_file, syn_config=cfg)
                except ImportError:
                    self.voice.synthesize_wav(text, wav_file)
            else:
                self.voice.synthesize(text, wav_file, length_scale=self.length_scale)
        return buf.getvalue()

    async def synthesize(self, text: str) -> bytes | None:
        return await asyncio.to_thread(self._run, text)


class HttpTTS:
    """OpenAI-compatible /v1/audio/speech (e.g. a Kokoro German FastAPI server)."""

    def __init__(
        self,
        s: Settings,
        voice: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = s.tts_url.rstrip("/") + "/v1/audio/speech"
        self.model = "kokoro"
        self.voice = voice
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(3.0, connect=0.5)
        )

    async def synthesize(self, text: str) -> bytes | None:
        r = await self.client.post(
            self.url,
            json={
                "model": self.model,
                "voice": self.voice,
                "input": text,
                "response_format": "wav",
            },
        )
        r.raise_for_status()
        return r.content


class FallbackTTS:
    """Use the primary TTS, but fall back on any failure without going silent."""

    def __init__(
        self,
        primary: TTS,
        fallback: TTS,
        on_fallback: Callable[[bool], Awaitable[None]] | None = None,
        retry_after_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.on_fallback = on_fallback
        self.failed = False
        # After a failure, skip the primary for a while: a hung sidecar would
        # otherwise cost the full read timeout on every sentence (T018 review).
        self.retry_after_s = retry_after_s
        self.clock = clock
        self._skip_until = 0.0

    async def synthesize(self, text: str) -> bytes | None:
        if self.failed and self.clock() < self._skip_until:
            return await self.fallback.synthesize(text)
        try:
            wav = await self.primary.synthesize(text)
        except Exception as exc:  # noqa: BLE001 — fallback is the whole point
            log.info("primary TTS unavailable (%s); using fallback", type(exc).__name__)
            self._skip_until = self.clock() + self.retry_after_s
            if not self.failed:
                self.failed = True
                if self.on_fallback:
                    result = self.on_fallback(True)
                    if inspect.isawaitable(result):
                        await result
            return await self.fallback.synthesize(text)
        if self.failed:
            self.failed = False
            if self.on_fallback:
                result = self.on_fallback(False)
                if inspect.isawaitable(result):
                    await result
        return wav


def make_session_tts(
    deps: Deps,
    voice_id: str,
    on_fallback: Callable[[bool], Awaitable[None]] | None = None,
) -> TTS:
    if deps.tts_backend == "none":
        return NoTTS()
    if deps.tts_backend == "piper":
        return deps.piper or deps.tts
    voice: VoiceInfo = resolve_voice(
        voice_id, deps.tts_backend, deps.tts_default_voice
    )
    if voice.engine == "piper":
        return deps.piper or deps.tts
    if deps.piper is None or deps.http_client is None:
        return deps.tts
    primary = HttpTTS(
        SimpleNamespace(tts_url=deps.tts_url),
        voice=voice.engine_voice,
        client=deps.http_client,
    )
    return FallbackTTS(primary, deps.piper, on_fallback=on_fallback)


def make_tts(s: Settings) -> TTS:
    """Legacy helper for callers that only need the shared/fallback engine."""
    if s.tts_backend == "none":
        return NoTTS()
    return PiperTTS(s)
