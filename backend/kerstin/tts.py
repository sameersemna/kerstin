"""Text-to-speech backends. Each returns a complete WAV file (bytes) per sentence."""

from __future__ import annotations

import asyncio
import io
import logging
import wave
from typing import Protocol

import httpx

from .config import Settings

log = logging.getLogger(__name__)


class TTS(Protocol):
    async def synthesize(self, text: str) -> bytes | None: ...


class NoTTS:
    async def synthesize(self, text: str) -> bytes | None:
        return None


class PiperTTS:
    """Local Piper voice. Default: de_DE-thorsten-high (download via `make voice`)."""

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

    def __init__(self, s: Settings) -> None:
        self.url = s.tts_url.rstrip("/") + "/v1/audio/speech"
        self.model = s.tts_model
        self.voice = s.tts_voice
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    async def synthesize(self, text: str) -> bytes | None:
        r = await self.client.post(
            self.url,
            json={"model": self.model, "voice": self.voice, "input": text, "response_format": "wav"},
        )
        r.raise_for_status()
        return r.content


def make_tts(s: Settings) -> TTS:
    if s.tts_backend == "none":
        return NoTTS()
    if s.tts_backend == "http":
        return HttpTTS(s)
    return PiperTTS(s)
