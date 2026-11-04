"""Loads persona, scenarios and feedback prompts from backend/prompts/."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    description: str
    opener: str


class PromptStore:
    def __init__(self, prompts_dir: Path) -> None:
        self.dir = prompts_dir

    @lru_cache(maxsize=1)  # noqa: B019 — one store per process
    def scenarios(self) -> dict[str, Scenario]:
        raw = json.loads((self.dir / "scenarios.json").read_text(encoding="utf-8"))
        return {k: Scenario(key=k, **v) for k, v in raw.items()}

    def scenario(self, key: str) -> Scenario:
        sc = self.scenarios()
        if key not in sc:
            raise KeyError(f"Unknown scenario {key!r}. Known: {', '.join(sc)}")
        return sc[key]

    def system_prompt(self, scenario_key: str) -> str:
        persona = (self.dir / "persona.md").read_text(encoding="utf-8")
        return persona.replace("{scenario}", self.scenario(scenario_key).description)

    def feedback_prompt(self, transcript: str) -> str:
        tpl = (self.dir / "feedback.md").read_text(encoding="utf-8")
        return tpl.replace("{transcript}", transcript)
