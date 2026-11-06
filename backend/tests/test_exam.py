"""Exam content, plan and moderation tests (no network, no GPU)."""

from __future__ import annotations

import copy
import json

import pytest

from kerstin.config import BACKEND_DIR
from kerstin.exam import MODERATION_PREFIX, is_moderation, load_presets, make_plan


def catalog() -> dict:
    return load_presets(BACKEND_DIR / "prompts")


def key(card: dict | None) -> str:
    assert card
    return str(card.get("title") or card.get("question") or card.get("situation"))


def test_real_exam_json_validates_and_pools_are_large_enough():
    data = catalog()
    assert len(data["presets"]) == 2
    assert len(data["pools"]["talk_topics"]) >= 8
    assert len(data["pools"]["kerstin_topics"]) >= 4
    assert len(data["pools"]["discussion_questions"]) >= 6
    assert len(data["pools"]["planning_tasks"]) >= 6


def test_make_plan_is_deterministic_and_has_no_repeated_cards():
    data = catalog()
    first = make_plan("praesentation_diskussion_planung", data, 1234)
    second = make_plan("praesentation_diskussion_planung", data, 1234)

    assert first == second
    assert [part.kind for part in first.parts] == [
        "prep",
        "learner_talk",
        "kerstin_talk",
        "dialog",
        "dialog",
    ]
    talk_cards = [
        key(part.card)
        for part in first.parts
        if part.kind in ("prep", "learner_talk")
    ]
    assert len(set(talk_cards)) == 1
    for kind in ("kerstin_talk", "dialog"):
        cards = [key(part.card) for part in first.parts if part.kind == kind]
        assert len(cards) == len(set(cards))


def test_make_plan_unknown_preset():
    with pytest.raises(ValueError):
        make_plan("does_not_exist", catalog(), 1)


def test_is_moderation():
    assert is_moderation({"role": "user", "content": MODERATION_PREFIX + "Teil 2"})
    assert not is_moderation({"role": "assistant", "content": MODERATION_PREFIX + "x"})
    assert not is_moderation({"role": "user", "content": "Teil 2"})


def test_broken_preset_kind_and_seconds_raise(tmp_path):
    data = copy.deepcopy(catalog())
    data["presets"]["praesentation_diskussion_planung"]["parts"][0]["kind"] = "nope"
    path = tmp_path / "exam.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_presets(tmp_path)

    data = copy.deepcopy(catalog())
    data["presets"]["praesentation_diskussion_planung"]["parts"][0]["seconds"] = 0
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_presets(tmp_path)


def test_broken_pool_size_raises(tmp_path):
    data = copy.deepcopy(catalog())
    data["pools"]["talk_topics"] = data["pools"]["talk_topics"][:7]
    path = tmp_path / "exam.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_presets(tmp_path)


def test_prompt_content_has_no_official_brand_names():
    text = (
        (BACKEND_DIR / "prompts" / "exam.json").read_text(encoding="utf-8")
        + (BACKEND_DIR / "prompts" / "exam.md").read_text(encoding="utf-8")
    ).lower()
    for brand in ("telc", "goethe", "testdaf", "ösd", "osd"):
        assert brand not in text
