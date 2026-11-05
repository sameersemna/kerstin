"""Ollama chat client (streaming and one-shot)."""

from __future__ import annotations

import json
import logging
import random
from collections.abc import AsyncIterator

import httpx

from .config import Settings

log = logging.getLogger(__name__)

Message = dict[str, str]


class OllamaLLM:
    def __init__(self, s: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.s = s
        self.base = s.ollama_url.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0))

    def _payload(
        self,
        messages: list[Message],
        stream: bool,
        max_tokens: int | None,
        temperature: float | None = None,
        model: str | None = None,
        keep_alive: str | None = None,
    ) -> dict:
        seed = self.s.llm_seed if self.s.llm_seed is not None else random.randrange(1, 2**31)
        payload: dict = {
            "model": model or self.s.ollama_model,
            "messages": messages,
            "stream": stream,
            "keep_alive": (
                self.s.ollama_keep_alive if keep_alive is None else keep_alive
            ),
            "options": {
                "temperature": (
                    self.s.llm_temperature if temperature is None else temperature
                ),
                "num_ctx": self.s.ollama_num_ctx,
                "seed": seed,
            },
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        # Only send "think" when we want it off/on explicitly; older Ollama ignores unknown keys.
        payload["think"] = self.s.llm_think
        return payload

    async def stream_chat(self, messages: list[Message]) -> AsyncIterator[str]:
        payload = self._payload(messages, stream=True, max_tokens=self.s.llm_max_reply_tokens)
        async with self.client.stream("POST", f"{self.base}/api/chat", json=payload) as r:
            if r.status_code >= 400:
                body = await r.aread()
                raise RuntimeError(f"Ollama error {r.status_code}: {body[:300]!r}")
            async for line in r.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if "error" in data:
                    raise RuntimeError(f"Ollama error: {data['error']}")
                piece = data.get("message", {}).get("content", "")
                if piece:
                    yield piece
                if data.get("done"):
                    break

    async def chat(
        self,
        messages: list[Message],
        max_tokens: int | None = 1200,
        temperature: float | None = None,
        model: str | None = None,
        keep_alive: str | None = None,
    ) -> str:
        payload = self._payload(
            messages,
            stream=False,
            max_tokens=max_tokens,
            temperature=temperature,
            model=model,
            keep_alive=keep_alive,
        )
        r = await self.client.post(f"{self.base}/api/chat", json=payload)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "")

    async def loaded_models(self) -> list[str]:
        r = await self.client.get(f"{self.base}/api/ps")
        r.raise_for_status()
        models = r.json().get("models", [])
        return [m.get("name") or m.get("model") for m in models if m.get("name") or m.get("model")]

    async def unload(self, model: str) -> None:
        try:
            r = await self.client.post(
                f"{self.base}/api/generate",
                json={"model": model, "keep_alive": 0},
            )
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001 — unload failures must not break feedback
            log.warning("Ollama unload failed for %s: %s", model, e)

    async def warmup(self, messages: list[Message]) -> None:
        """Load the model and cache the prompt prefix; never raises."""
        payload = self._payload(messages, stream=False, max_tokens=1)
        try:
            r = await self.client.post(f"{self.base}/api/chat", json=payload)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            log.warning("LLM warm-up failed: %s", e)

    async def health(self) -> dict:
        try:
            r = await self.client.get(f"{self.base}/api/tags", timeout=3.0)
            r.raise_for_status()
            names = [m.get("name") for m in r.json().get("models", [])]
            return {"ok": True, "model_available": self.s.ollama_model in names}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
