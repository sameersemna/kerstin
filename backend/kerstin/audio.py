"""Small audio helpers. Client sends 16 kHz mono signed 16-bit little-endian PCM."""

from __future__ import annotations

import io
import math
import operator
import wave
from array import array

SAMPLE_RATE = 16_000

try:
    _sumprod = math.sumprod  # Python 3.12+
except AttributeError:  # Python 3.11
    def _sumprod(a, b):
        return sum(map(operator.mul, a, b))


def pcm16_to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def pcm16_duration_s(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> float:
    return len(pcm) / 2 / sample_rate


def pcm16_rms_dbfs(pcm: bytes) -> float:
    """RMS level of 16-bit mono PCM relative to full scale (32768)."""
    if not pcm:
        return -120.0
    usable = len(pcm) - (len(pcm) % 2)
    if usable == 0:
        return -120.0
    samples = array("h")
    samples.frombytes(pcm[:usable])
    total = _sumprod(samples, samples)
    if total == 0:
        return -120.0
    rms = math.sqrt(total / len(samples))
    return max(-120.0, 20.0 * math.log10(rms / 32768.0))
