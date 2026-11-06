"""HTTP API tests for the opt-in mistake summary/clear endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

import kerstin.main as main_module
from kerstin.config import BACKEND_DIR
from kerstin.mistakes import MistakeLog
from kerstin.prompts import PromptStore
from kerstin.session import Deps


def make_client(monkeypatch, tmp_path: Path, *, enabled: bool = True) -> tuple[TestClient, MistakeLog | None]:
    mistakes = (
        MistakeLog(tmp_path / "mistakes.sqlite3") if enabled else None
    )
    deps = Deps(
        stt=None,
        llm=None,
        tts=None,
        prompts=PromptStore(BACKEND_DIR / "prompts"),
        mistakes=mistakes,
    )
    monkeypatch.setattr(main_module, "deps", deps)
    return TestClient(main_module.app), mistakes


def test_get_empty_does_not_create_the_database(monkeypatch, tmp_path):
    client, mistakes = make_client(monkeypatch, tmp_path)
    assert mistakes is not None

    response = client.get("/api/mistakes")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "sessions": 0,
        "categories": [],
    }
    assert not mistakes.path.exists()


def test_get_after_record(monkeypatch, tmp_path):
    client, mistakes = make_client(monkeypatch, tmp_path)
    assert mistakes is not None
    asyncio.run(mistakes.record("freies_gespraech", "en", ["kasus", "verbposition"]))

    response = client.get("/api/mistakes")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "sessions": 1,
        "categories": [
            {"key": "kasus", "label": "Kasus", "count": 1},
            {"key": "verbposition", "label": "Verbposition", "count": 1},
        ],
    }


def test_delete_clears_the_log(monkeypatch, tmp_path):
    client, mistakes = make_client(monkeypatch, tmp_path)
    assert mistakes is not None
    asyncio.run(mistakes.record("freies_gespraech", "en", ["kasus"]))

    response = client.delete("/api/mistakes")

    assert response.status_code == 200
    assert response.json() == {"cleared": True}
    assert client.get("/api/mistakes").json() == {
        "enabled": True,
        "sessions": 0,
        "categories": [],
    }
    assert mistakes.path.exists()


def test_disabled_log(monkeypatch, tmp_path):
    client, mistakes = make_client(monkeypatch, tmp_path, enabled=False)
    assert mistakes is None

    assert client.get("/api/mistakes").json() == {
        "enabled": False,
        "sessions": 0,
        "categories": [],
    }
    assert client.delete("/api/mistakes").status_code == 404
