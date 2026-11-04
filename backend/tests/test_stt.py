"""WhisperCppSTT tests with httpx.MockTransport (no network, no GPU)."""

import httpx
import pytest

from kerstin.config import Settings
from kerstin.stt import WhisperCppSTT, make_stt


def make_settings(**overrides) -> Settings:
    values = {
        "stt_backend": "whispercpp",
        "stt_url": "http://stt.test",
        "stt_language": "de",
    }
    values.update(overrides)
    return Settings(**values)


async def test_posts_multipart_to_inference_with_language_and_wav():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["content_type"] = request.headers.get("content-type", "")
        seen["body"] = request.content
        return httpx.Response(200, json={"text": "Hallo."})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    stt = WhisperCppSTT(make_settings(), client=client)
    try:
        await stt.transcribe(b"\x00\x00" * 1600)
    finally:
        await client.aclose()

    assert seen["url"] == "http://stt.test/inference"
    assert "multipart/form-data" in seen["content_type"]
    assert b'name="language"' in seen["body"]
    assert b"\r\n\r\nde\r\n" in seen["body"]
    assert b'name="response_format"' in seen["body"]
    assert b'name="temperature"' in seen["body"]
    assert b"RIFF" in seen["body"]


async def test_response_text_is_stripped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "  Am Wochenende war ich am See.  "})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    stt = WhisperCppSTT(make_settings(), client=client)
    try:
        text = await stt.transcribe(b"\x00\x00" * 1600)
    finally:
        await client.aclose()

    assert text == "Am Wochenende war ich am See."


async def test_http_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    stt = WhisperCppSTT(make_settings(), client=client)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await stt.transcribe(b"\x00\x00" * 1600)
    finally:
        await client.aclose()


def test_make_stt_returns_whispercpp():
    stt = make_stt(make_settings())
    assert isinstance(stt, WhisperCppSTT)
