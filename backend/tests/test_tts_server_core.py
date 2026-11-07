"""Tests for the torch-free Kokoro sidecar helpers."""

from __future__ import annotations

import importlib.util
import io
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE_PATH = ROOT / "tts_server" / "core.py"


def load_core():
    spec = importlib.util.spec_from_file_location("kerstin_tts_core", CORE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


core = load_core()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"input": "", "voice": "thorsten", "response_format": "wav"},
        {"input": "   ", "voice": "thorsten", "response_format": "wav"},
        {"input": "x" * 601, "voice": "thorsten", "response_format": "wav"},
        {"input": "Hallo", "voice": "thorsten", "response_format": "mp3"},
        {"input": "Hallo", "voice": "unknown", "response_format": "wav"},
        {"input": "Hallo", "voice": "thorsten", "response_format": "wav", "speed": 0.69},
        {"input": "Hallo", "voice": "thorsten", "response_format": "wav", "speed": 1.31},
        {"input": "Hallo", "voice": "thorsten", "response_format": "wav", "speed": "fast"},
    ],
)
def test_validate_request_rejects_invalid(payload):
    with pytest.raises(core.RequestError):
        core.validate_request(payload, {"thorsten"})


def test_validate_request_accepts_defaults():
    request = core.validate_request(
        {"input": "Hallo", "voice": "thorsten", "response_format": "wav"},
        {"thorsten"},
    )
    assert request.text == "Hallo"
    assert request.voice == "thorsten"
    assert request.speed == 1.0

    request = core.validate_request(
        {"input": "Hallo", "voice": "thorsten", "response_format": "wav", "speed": 1.3},
        {"thorsten"},
    )
    assert request.speed == 1.3


def test_fix_phonemes_replaces_short_u():
    assert core.fix_phonemes("bʏkə") == "bykə"
    assert core.fix_phonemes("normal") == "normal"


def test_float_to_wav_header_and_clipping():
    wav_bytes = core.float_to_wav([0.0, 1.5, -1.5], rate=24000)

    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 24000
        assert wav.getnframes() == 3
        frames = wav.readframes(wav.getnframes())

    values = [int.from_bytes(frames[i : i + 2], "little", signed=True) for i in range(0, 6, 2)]
    assert values[0] == 0
    assert values[1] == 32767
    assert values[2] == -32767


def test_voice_allowlist_parser_default_and_custom():
    assert core.parse_voice_allowlist(None) == ("kerstin", "thorsten")
    assert core.parse_voice_allowlist("kerstin, thorsten,") == ("kerstin", "thorsten")
    assert core.parse_voice_allowlist("kerstin") == ("kerstin",)
