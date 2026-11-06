"""Frontend vendor visibility and no-CDN tests (no downloads)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import kerstin.main as main_module

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


class FakeLLM:
    async def health(self) -> dict:
        return {"ok": True}


def make_client(monkeypatch, frontend_dir: Path) -> TestClient:
    deps = SimpleNamespace(thermal=None, llm=FakeLLM())
    monkeypatch.setattr(main_module, "deps", deps)
    monkeypatch.setattr(main_module.settings, "frontend_dir", frontend_dir)
    return TestClient(main_module.app)


def test_health_reports_missing_vendor_assets(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["frontend_vendor"] is False


def test_health_reports_present_vendor_assets(monkeypatch, tmp_path):
    for name in main_module.FRONTEND_VENDOR_FILES:
        path = tmp_path / "vendor" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    client = make_client(monkeypatch, tmp_path)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["frontend_vendor"] is True


def test_frontend_has_no_external_asset_urls():
    for name in ("index.html", "app.js"):
        text = (FRONTEND_DIR / name).read_text(encoding="utf-8")
        assert "http://" not in text
        assert "https://" not in text
