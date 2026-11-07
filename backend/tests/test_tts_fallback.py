"""FallbackTTS behavior, including one notification per failure streak."""

from __future__ import annotations

import pytest

from kerstin.tts import FallbackTTS


class FakeTTS:
    def __init__(self, value=b"audio", error=None):
        self.value = value
        self.error = error
        self.calls = 0

    async def synthesize(self, text):
        self.calls += 1
        if self.error:
            raise self.error
        return self.value


async def test_primary_ok_does_not_notify():
    events = []
    primary = FakeTTS(b"primary")
    tts = FallbackTTS(primary, FakeTTS(b"fallback"), events.append)

    assert await tts.synthesize("Hallo") == b"primary"
    assert events == []
    assert primary.calls == 1


@pytest.mark.parametrize("error", [RuntimeError("down"), TimeoutError()])
async def test_failure_uses_fallback_once_per_streak(error):
    events = []
    primary = FakeTTS(b"primary", error=error)
    fallback = FakeTTS(b"fallback")
    tts = FallbackTTS(primary, fallback, events.append)

    assert await tts.synthesize("Hallo") == b"fallback"
    assert await tts.synthesize("Hallo") == b"fallback"
    assert events == [True]
    assert fallback.calls == 2

    primary.error = None
    assert await tts.synthesize("Hallo") == b"primary"
    assert events == [True, False]
