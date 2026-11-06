"""HTTP tests for the exam preset list."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient

import kerstin.main as main_module


def test_exams_lists_both_presets_in_file_order():
    client = TestClient(main_module.app)

    response = client.get("/api/exams")

    assert response.status_code == 200
    data = response.json()
    assert [item["key"] for item in data] == [
        "praesentation_diskussion_planung",
        "vortrag_diskussion",
    ]
    assert all(item["title"] and item["note"] for item in data)
    assert "offizielle" in data[0]["note"]


def test_exams_missing_file_returns_empty_and_logs_warning(
    monkeypatch, tmp_path, caplog
):
    monkeypatch.setattr(main_module.settings, "prompts_dir", tmp_path)
    client = TestClient(main_module.app)

    with caplog.at_level(logging.WARNING, logger="kerstin.main"):
        response = client.get("/api/exams")

    assert response.status_code == 200
    assert response.json() == []
    assert "exam presets unavailable" in caplog.text
