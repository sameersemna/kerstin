"""Voice catalog/default and Piper filtering tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kerstin.config import Settings
from kerstin.voices import (
    VOICES,
    catalog_for_backend,
    default_voice_id,
    resolve_voice,
)


def test_catalog_has_exactly_three_production_voices():
    assert [voice.id for voice in VOICES] == [
        "kokoro-kerstin",
        "kokoro-thorsten",
        "piper-thorsten",
    ]
    assert all(voice.id != "kokoro-victoria" for voice in VOICES)


def test_piper_backend_filters_to_piper_voice():
    voices = catalog_for_backend("piper")
    assert [voice.id for voice in voices] == ["piper-thorsten"]
    assert default_voice_id("piper", "kokoro-kerstin") == "piper-thorsten"
    assert resolve_voice("kokoro-kerstin", "piper", "kokoro-kerstin").id == "piper-thorsten"


def test_auto_default_and_unknown_voice_resolution():
    assert default_voice_id("auto", "kokoro-kerstin") == "kokoro-kerstin"
    assert resolve_voice(None, "auto", "kokoro-kerstin").id == "kokoro-kerstin"
    assert resolve_voice("missing", "auto", "kokoro-kerstin").id == "kokoro-kerstin"


def test_bad_configured_default_fails_at_startup():
    with pytest.raises(ValidationError, match="not in the voice catalog"):
        Settings(tts_voice_default="kokoro-victoria")
