"""OllamaLLM seed and warm-up tests with httpx.MockTransport (no network)."""

import json

import httpx

from kerstin.config import Settings
from kerstin.llm import OllamaLLM

MESSAGES = [
    {"role": "system", "content": "Du bist Kerstin."},
    {"role": "assistant", "content": "Hey, schön, dass du da bist!"},
]


def make_settings(**overrides) -> Settings:
    values = {"ollama_url": "http://ollama.test", "ollama_model": "qwen3:14b"}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def make_llm(handler, **overrides) -> OllamaLLM:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OllamaLLM(make_settings(**overrides), client=client)


async def test_without_seed_two_requests_get_different_seeds() -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "ok"}})

    llm = make_llm(handler)
    try:
        await llm.chat([{"role": "user", "content": "Hallo"}])
        await llm.chat([{"role": "user", "content": "Hallo"}])
    finally:
        await llm.client.aclose()

    seeds = [payload["options"]["seed"] for payload in payloads]
    assert len(seeds) == 2
    assert all(isinstance(seed, int) for seed in seeds)
    assert seeds[0] != seeds[1]


async def test_fixed_seed_is_sent() -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "ok"}})

    llm = make_llm(handler, llm_seed=42)
    try:
        await llm.chat([{"role": "user", "content": "Hallo"}])
    finally:
        await llm.client.aclose()

    assert payloads[0]["options"]["seed"] == 42


async def test_chat_temperature_override() -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "ok"}})

    llm = make_llm(handler, llm_temperature=0.8)
    try:
        await llm.chat([{"role": "user", "content": "Hallo"}], temperature=0.2)
        await llm.chat([{"role": "user", "content": "Hallo"}])
    finally:
        await llm.client.aclose()

    assert payloads[0]["options"]["temperature"] == 0.2
    assert payloads[1]["options"]["temperature"] == 0.8


async def test_chat_model_and_keep_alive_overrides() -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "ok"}})

    llm = make_llm(handler, ollama_model="gemma4:26b")
    try:
        await llm.chat(
            [{"role": "user", "content": "Hallo"}],
            model="gemma4:31b",
            keep_alive="0",
        )
    finally:
        await llm.client.aclose()

    assert payloads[0]["model"] == "gemma4:31b"
    assert payloads[0]["keep_alive"] == "0"


async def test_loaded_models_parses_ps() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url).endswith("/api/ps")
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "gemma4:26b"},
                    {"model": "llama3.2:1b"},
                ]
            },
        )

    llm = make_llm(handler)
    try:
        assert await llm.loaded_models() == ["gemma4:26b", "llama3.2:1b"]
    finally:
        await llm.client.aclose()


async def test_unload_posts_keep_alive_zero() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"response": ""})

    llm = make_llm(handler)
    try:
        await llm.unload("gemma4:31b")
    finally:
        await llm.client.aclose()

    assert seen["method"] == "POST"
    assert seen["url"] == "http://ollama.test/api/generate"
    assert seen["payload"] == {"model": "gemma4:31b", "keep_alive": 0}


async def test_unload_swallows_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    llm = make_llm(handler)
    try:
        await llm.unload("gemma4:31b")
    finally:
        await llm.client.aclose()


async def test_warmup_payload() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": ""}})

    llm = make_llm(handler)
    try:
        await llm.warmup(MESSAGES)
    finally:
        await llm.client.aclose()

    payload = seen["payload"]
    assert seen["url"] == "http://ollama.test/api/chat"
    assert payload["model"] == "qwen3:14b"
    assert payload["messages"] == MESSAGES
    assert payload["stream"] is False
    assert payload["keep_alive"] == "10m"
    assert payload["options"]["num_predict"] == 1
    assert payload["options"]["num_ctx"] == 8192
    assert payload["think"] is False


async def test_warmup_swallows_http_500() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    llm = make_llm(handler)
    try:
        await llm.warmup(MESSAGES)
    finally:
        await llm.client.aclose()


async def test_warmup_swallows_connect_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    llm = make_llm(handler)
    try:
        await llm.warmup(MESSAGES)
    finally:
        await llm.client.aclose()


async def test_warmup_swallows_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    llm = make_llm(handler)
    try:
        await llm.warmup(MESSAGES)
    finally:
        await llm.client.aclose()
