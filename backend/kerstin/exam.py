"""Data-driven exam plans for B2 speaking practice."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

MODERATION_PREFIX = "[Moderation] "
KINDS = {"prep", "learner_talk", "kerstin_talk", "dialog"}
POOL_MINIMUMS = {
    "talk_topics": 8,
    "kerstin_topics": 4,
    "discussion_questions": 6,
    "planning_tasks": 6,
}
POOL_ALIASES = {
    "talk": "talk_topics",
    "talk_topics": "talk_topics",
    "kerstin": "kerstin_topics",
    "kerstin_topics": "kerstin_topics",
    "discussion": "discussion_questions",
    "discussion_questions": "discussion_questions",
    "planning": "planning_tasks",
    "planning_tasks": "planning_tasks",
}


@dataclass(frozen=True)
class ExamPart:
    kind: str
    title: str
    seconds: int
    ui_text: str
    card: dict | None = None
    talk_words: int | None = None


@dataclass(frozen=True)
class ExamPlan:
    preset: str
    title: str
    note: str
    greeting: str
    parts: list[ExamPart]


def is_moderation(message: dict) -> bool:
    return (
        message.get("role") == "user"
        and str(message.get("content", "")).startswith(MODERATION_PREFIX)
    )


def _require_text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: expected a non-empty string")
    return value


def _validate_card(card: object, where: str, *, points: int | None, aspects: int | None) -> None:
    if not isinstance(card, dict):
        raise ValueError(f"{where}: expected an object")  # noqa: TRY004  # noqa: TRY004
    if "title" in card:
        _require_text(card["title"], f"{where}.title")
    elif "question" in card:
        _require_text(card["question"], f"{where}.question")
    elif "situation" in card:
        _require_text(card["situation"], f"{where}.situation")
    else:
        raise ValueError(f"{where}: missing title, question or situation")
    if points is not None:
        values = card.get("points")
        if not isinstance(values, list) or len(values) != points:
            raise ValueError(f"{where}: expected {points} points")
        for index, value in enumerate(values):
            _require_text(value, f"{where}.points[{index}]")
    if aspects is not None:
        values = card.get("aspects")
        if not isinstance(values, list) or len(values) != aspects:
            raise ValueError(f"{where}: expected {aspects} aspects")
        for index, value in enumerate(values):
            _require_text(value, f"{where}.aspects[{index}]")


def load_presets(directory: Path) -> dict:
    """Load and validate exam.json. Return the validated catalog."""
    path = Path(directory) / "exam.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("exam.json: expected an object")  # noqa: TRY004
    _require_text(data.get("greeting"), "greeting")

    presets = data.get("presets")
    if not isinstance(presets, dict) or not presets:
        raise ValueError("exam.json: presets must be a non-empty object")
    for key, preset in presets.items():
        where = f"presets.{key}"
        if not isinstance(preset, dict):
            raise ValueError(f"{where}: expected an object")  # noqa: TRY004
        _require_text(preset.get("title"), f"{where}.title")
        _require_text(preset.get("note"), f"{where}.note")
        parts = preset.get("parts")
        if not isinstance(parts, list) or not parts:
            raise ValueError(f"{where}.parts: expected a non-empty list")
        for index, part in enumerate(parts):
            part_where = f"{where}.parts[{index}]"
            if not isinstance(part, dict):
                raise ValueError(f"{part_where}: expected an object")  # noqa: TRY004
            kind = part.get("kind")
            if kind not in KINDS:
                raise ValueError(f"{part_where}.kind: unexpected {kind!r}")
            _require_text(part.get("title"), f"{part_where}.title")
            _require_text(part.get("ui_text"), f"{part_where}.ui_text")
            seconds = part.get("seconds")
            if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds <= 0:
                raise ValueError(f"{part_where}.seconds: expected a positive integer")
            talk_words = part.get("talk_words")
            if talk_words is not None and (
                not isinstance(talk_words, int)
                or isinstance(talk_words, bool)
                or talk_words <= 0
            ):
                raise ValueError(
                    f"{part_where}.talk_words: expected a positive integer"
                )

    pool_data = data.get("pools")
    if not isinstance(pool_data, dict):
        raise ValueError("exam.json: pools must be an object")  # noqa: TRY004  # noqa: TRY004
    for pool_name, minimum in POOL_MINIMUMS.items():
        cards = pool_data.get(pool_name)
        if not isinstance(cards, list) or len(cards) < minimum:
            raise ValueError(
                f"pools.{pool_name}: expected at least {minimum} cards"
            )
        for index, card in enumerate(cards):
            if pool_name in ("talk_topics", "kerstin_topics"):
                _validate_card(card, f"pools.{pool_name}[{index}]", points=4, aspects=None)
            elif pool_name == "discussion_questions":
                _validate_card(
                    card, f"pools.{pool_name}[{index}]", points=None, aspects=2
                )
            else:
                _validate_card(card, f"pools.{pool_name}[{index}]", points=4, aspects=None)
    return data


def _card_key(card: dict) -> str:
    return str(card.get("title") or card.get("question") or card.get("situation"))


def _pick(
    pool: list[dict],
    used: set[str],
    rng: random.Random,
    where: str,
    pinned: str | None = None,
) -> dict:
    if pinned is not None:
        matches = [
            card
            for card in pool
            if pinned
            in {
                card.get("title"),
                card.get("question"),
                card.get("situation"),
            }
        ]
        if not matches:
            raise ValueError(f"{where}: no card titled {pinned!r}")
        card = matches[0]
        if _card_key(card) in used:
            raise ValueError(f"{where}: pinned card {pinned!r} is repeated")
        used.add(_card_key(card))
        return card
    available = [card for card in pool if _card_key(card) not in used]
    if not available:
        raise ValueError(f"{where}: no unused card left")
    card = rng.choice(available)
    used.add(_card_key(card))
    return card


def make_plan(
    preset_key: str,
    pools: dict,
    seed: int,
    cards: dict[str, str] | None = None,
) -> ExamPlan:
    """Resolve a deterministic, non-repeating card plan for one preset.

    ``cards`` pins a card by title/question/situation. Keys may be pool names
    or the short aliases ``talk``, ``kerstin``, ``discussion`` and ``planning``.
    """
    presets = pools.get("presets")
    if not isinstance(presets, dict) or preset_key not in presets:
        raise ValueError(f"unknown exam preset {preset_key!r}")
    preset = presets[preset_key]
    pool_data = pools.get("pools")
    if not isinstance(pool_data, dict):
        raise ValueError("exam.json: pools must be an object")  # noqa: TRY004
    pinned: dict[str, str] = {}
    if cards:
        for key, value in cards.items():
            pool_name = POOL_ALIASES.get(key)
            if pool_name is None:
                raise ValueError(f"unknown card pool {key!r}")
            pinned[pool_name] = value
    rng = random.Random(seed)
    used: dict[str, set[str]] = {
        "talk_topics": set(),
        "kerstin_topics": set(),
        "discussion_questions": set(),
        "planning_tasks": set(),
    }
    pending_talk: dict | None = None
    parts: list[ExamPart] = []

    for raw in preset["parts"]:
        kind = raw["kind"]
        if kind in ("prep", "learner_talk"):
            if pending_talk is None:
                pending_talk = _pick(
                    pool_data["talk_topics"],
                    used["talk_topics"],
                    rng,
                    "talk_topics",
                    pinned.get("talk_topics"),
                )
            card = pending_talk
            if kind == "learner_talk":
                pending_talk = None
        elif kind == "kerstin_talk":
            card = _pick(
                pool_data["kerstin_topics"],
                used["kerstin_topics"],
                rng,
                "kerstin_topics",
                pinned.get("kerstin_topics"),
            )
        else:
            if "plan" in str(raw["title"]).lower():
                card = _pick(
                    pool_data["planning_tasks"],
                    used["planning_tasks"],
                    rng,
                    "planning_tasks",
                    pinned.get("planning_tasks"),
                )
            else:
                card = _pick(
                    pool_data["discussion_questions"],
                    used["discussion_questions"],
                    rng,
                    "discussion_questions",
                    pinned.get("discussion_questions"),
                )
        parts.append(
            ExamPart(
                kind=kind,
                title=raw["title"],
                seconds=raw["seconds"],
                ui_text=raw["ui_text"],
                card=card,
                talk_words=raw.get("talk_words"),
            )
        )

    return ExamPlan(
        preset=preset_key,
        title=preset["title"],
        note=preset["note"],
        greeting=pools["greeting"],
        parts=parts,
    )
