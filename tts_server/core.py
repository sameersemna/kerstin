"""Pure request/WAV helpers for the Kokoro sidecar (no torch import)."""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass

import numpy as np

MAX_INPUT_CHARS = 600


class RequestError(ValueError):
    """Invalid OpenAI-style speech request."""


@dataclass(frozen=True)
class SpeechRequest:
    text: str
    voice: str
    speed: float = 1.0


def validate_request(payload: dict, voices: set[str] | list[str]) -> SpeechRequest:
    if not isinstance(payload, dict):
        raise RequestError("request body must be a JSON object")
    text = payload.get("input")
    if not isinstance(text, str) or not text.strip():
        raise RequestError("input must be a non-empty string")
    if len(text) > MAX_INPUT_CHARS:
        raise RequestError(f"input must be at most {MAX_INPUT_CHARS} characters")
    if payload.get("response_format") != "wav":
        raise RequestError("response_format must be 'wav'")
    voice = payload.get("voice")
    if not isinstance(voice, str) or voice not in set(voices):
        raise RequestError(f"unknown voice: {voice!r}")
    speed = payload.get("speed", 1.0)
    if isinstance(speed, bool) or not isinstance(speed, (int, float)):
        raise RequestError("speed must be a number between 0.7 and 1.3")
    speed = float(speed)
    if not 0.7 <= speed <= 1.3:
        raise RequestError("speed must be between 0.7 and 1.3")
    return SpeechRequest(text=text, voice=voice, speed=speed)


def fix_phonemes(ps: str) -> str:
    return ps.replace("ʏ", "y")


def float_to_wav(samples, rate: int = 24000) -> bytes:
    # Vectorised: a per-sample Python loop cost ~25 ms per 4 s of audio,
    # a quarter of the CUDA synthesis time (T012 review).
    clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = np.rint(clipped * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm.tobytes())
    return buf.getvalue()
