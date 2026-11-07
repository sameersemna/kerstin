"""HTTP voice catalog and health shape tests (no network)."""

from __future__ import annotations

import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

import kerstin.main as main_module


class FakeLLM:
    async def health(self):
        return {"ok": True}


def client_with_deps(monkeypatch, backend="auto"):
    deps = SimpleNamespace(
        llm=FakeLLM(),
        thermal=None,
        tts_backend=backend,
        tts_default_voice="kokoro-kerstin",
        http_client=object(),
    )
    monkeypatch.setattr(main_module, "deps", deps)
    monkeypatch.setattr(main_module, "_voice_health_cache", (0.0, None))
    return TestClient(main_module.app)


def test_voices_sidecar_up_and_down(monkeypatch):
    client = client_with_deps(monkeypatch)
    monkeypatch.setattr(
        main_module,
        "_voice_health_cache",
        (time.monotonic(), {"ok": True, "gpu_resident": True, "voices": ["kerstin", "thorsten"]}),
    )
    response = client.get("/api/voices")
    assert response.status_code == 200
    data = response.json()
    assert data["default"] == "kokoro-kerstin"
    assert [voice["id"] for voice in data["voices"]] == [
        "kokoro-kerstin",
        "kokoro-thorsten",
        "piper-thorsten",
    ]
    assert all(voice["available"] for voice in data["voices"])

    monkeypatch.setattr(main_module, "_voice_health_cache", (time.monotonic(), None))
    response = client.get("/api/voices")
    data = response.json()
    assert [voice["available"] for voice in data["voices"]] == [False, False, True]


def test_voices_piper_mode_filters_catalog(monkeypatch):
    client = client_with_deps(monkeypatch, backend="piper")
    response = client.get("/api/voices")

    data = response.json()
    assert data["default"] == "piper-thorsten"
    assert [voice["id"] for voice in data["voices"]] == ["piper-thorsten"]
    assert data["voices"][0]["available"] is True


def test_health_reports_tts_sidecar(monkeypatch):
    client = client_with_deps(monkeypatch)
    monkeypatch.setattr(
        main_module,
        "_voice_health_cache",
        (time.monotonic(), {"ok": True, "gpu_resident": False, "voices": ["kerstin"]}),
    )
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["tts"] == {
        "default": "kokoro-kerstin",
        "kokoro": {"ok": True, "gpu_resident": False},
    }
