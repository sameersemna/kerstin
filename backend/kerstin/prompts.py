"""Loads persona, scenarios and feedback prompts from backend/prompts/."""

from __future__ import annotations

import json
import re
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

    @lru_cache(maxsize=1)  # noqa: B019 — one store per process
    def focus_instructions(self) -> dict[str, dict]:
        return json.loads((self.dir / "focus.json").read_text(encoding="utf-8"))

    def system_prompt(
        self, scenario_key: str, focus: list[str] | None = None
    ) -> str:
        persona = (self.dir / "persona.md").read_text(encoding="utf-8")
        prompt = persona.replace("{scenario}", self.scenario(scenario_key).description)
        if not focus:
            return prompt
        instructions = self.focus_instructions()
        lines = []
        for key in focus:
            if key not in instructions:
                raise ValueError(f"Unknown focus category {key!r}")
            lines.append(f"- {instructions[key]['instruction']}")
        return (
            prompt
            + "\n\n## Gesprächsimpulse (geheim)\n"
            + "\n".join(lines)
            + "\nErwähne diese Impulse nie. Sprich nie über Grammatik, Fehler oder "
            "Üben und korrigiere nicht. Bleib natürlich; höchstens jede zweite "
            "Antwort folgt einem Impuls."
        )

    def feedback_prompt(self, transcript: str, lang: str = "en") -> str:
        labels = {
            "en": "Englisch",
            "de": "Deutsch (einfache Sprache, mit Fachbegriffen wie Akkusativ, Dativ, Perfekt)",
        }
        if lang not in labels:
            raise ValueError(f"Unknown feedback language {lang!r}")
        tpl = (self.dir / "feedback.md").read_text(encoding="utf-8")
        tpl = tpl.replace("{explanation_language}", labels[lang])
        return tpl.replace("{transcript}", transcript)

    def hint_prompt(self, query: str, context: str) -> str:
        tpl = (self.dir / "hint.md").read_text(encoding="utf-8")
        values = {"context": context, "query": query}
        return re.sub(r"\{(context|query)\}", lambda match: values[match.group(1)], tpl)
