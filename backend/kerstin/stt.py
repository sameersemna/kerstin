"""Speech-to-text backends.

- HttpSTT: any OpenAI-compatible /v1/audio/transcriptions server
  (speaches / faster-whisper-server / LocalAI ...). Default, because Sameer
  already runs Whisper on the GB10.
- LocalSTT: faster-whisper in-process (needs CTranslate2 with CUDA on aarch64;
  see docs/STATUS.md).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

import httpx

from .audio import pcm16_to_wav
from .config import Settings

log = logging.getLogger(__name__)


class STT(Protocol):
    async def transcribe(self, pcm16: bytes) -> str: ...


class HttpSTT:
    def __init__(self, s: Settings) -> None:
        self.url = s.stt_url.rstrip("/") + "/v1/audio/transcriptions"
        self.model = s.stt_model
        self.language = s.stt_language
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    async def transcribe(self, pcm16: bytes) -> str:
        wav = pcm16_to_wav(pcm16)
        files = {"file": ("utterance.wav", wav, "audio/wav")}
        data = {"model": self.model, "language": self.language, "response_format": "json"}
        r = await self.client.post(self.url, files=files, data=data)
        r.raise_for_status()
        return (r.json().get("text") or "").strip()


class WhisperCppSTT:
    """whisper.cpp server: POST /inference as multipart, not OpenAI-compatible.

    The GB10 server runs without ``-l`` (default English), so every request
    must send ``language`` explicitly.
    """

    def __init__(self, s: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.url = s.stt_url.rstrip("/") + s.stt_inference_path
        self.language = s.stt_language
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0))

    async def transcribe(self, pcm16: bytes) -> str:
        wav = pcm16_to_wav(pcm16)
        files = {"file": ("utterance.wav", wav, "audio/wav")}
        data = {
            "language": self.language,
            "response_format": "json",
            "temperature": "0.0",
        }
        r = await self.client.post(self.url, files=files, data=data)
        r.raise_for_status()
        return (r.json().get("text") or "").strip()


class LocalSTT:
    def __init__(self, s: Settings) -> None:
        from faster_whisper import WhisperModel  # lazy: optional dependency

        model_name = s.stt_model.split("/")[-1].replace("faster-whisper-", "")
        log.info("Loading faster-whisper model %s on %s", model_name, s.stt_local_device)
        self.model = WhisperModel(
            model_name, device=s.stt_local_device, compute_type=s.stt_local_compute_type
        )
        self.language = s.stt_language

    def _run(self, pcm16: bytes) -> str:
        import numpy as np

        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self.model.transcribe(
            audio, language=self.language, beam_size=1, vad_filter=False
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    async def transcribe(self, pcm16: bytes) -> str:
        return await asyncio.to_thread(self._run, pcm16)


def make_stt(s: Settings) -> STT:
    if s.stt_backend == "local":
        return LocalSTT(s)
    if s.stt_backend == "whispercpp":
        return WhisperCppSTT(s)
    return HttpSTT(s)
