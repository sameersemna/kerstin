"""Loads persona, scenarios and feedback prompts from backend/prompts/."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .exam import ExamPlan


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    description: str
    opener: str


def _format_exam_cards(plan: ExamPlan) -> str:
    blocks: list[str] = []
    for index, part in enumerate(plan.parts, 1):
        card = part.card or {}
        owner = "Karte von Kerstin" if part.kind == "kerstin_talk" else "Karte der Lernenden"
        blocks.append(f"### Teil {index} – {part.title} ({owner})")
        if "question" in card:
            blocks.append(f"Frage: {card['question']}")
            blocks.append("Aspekte:")
            blocks.extend(f"- {aspect}" for aspect in card.get("aspects", []))
        else:
            label = "Situation" if "situation" in card else "Titel"
            blocks.append(f"{label}: {card.get('situation') or card.get('title')}")
            values = card.get("points") or []
            if values:
                blocks.append("Punkte:")
                blocks.extend(f"- {point}" for point in values)
        blocks.append("")
    return "\n".join(blocks).rstrip()


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

    def exam_system_prompt(self, plan: ExamPlan) -> str:
        persona = (self.dir / "persona.md").read_text(encoding="utf-8")
        prompt = persona.replace(
            "{scenario}",
            "Wir machen eine B2-Sprechübung zu zweit. Ein Moderator führt durch "
            "die Teile; du bist Mitprüfling.",
        )
        talk_words = next(
            (
                part.talk_words
                for part in plan.parts
                if part.kind == "kerstin_talk" and part.talk_words
            ),
            130,
        )
        cards = _format_exam_cards(plan)
        addendum = (self.dir / "exam.md").read_text(encoding="utf-8")
        addendum = addendum.replace("{talk_words}", str(talk_words))
        addendum = addendum.replace("{cards}", cards)
        return prompt + "\n\n" + addendum

    def _explanation_language(self, lang: str) -> str:
        labels = {
            "en": "Englisch",
            "de": "Deutsch (einfache Sprache, mit Fachbegriffen wie Akkusativ, Dativ, Perfekt)",
        }
        if lang not in labels:
            raise ValueError(f"Unknown feedback language {lang!r}")
        return labels[lang]

    def feedback_prompt(self, transcript: str, lang: str = "en") -> str:
        tpl = (self.dir / "feedback.md").read_text(encoding="utf-8")
        tpl = tpl.replace("{explanation_language}", self._explanation_language(lang))
        return tpl.replace("{transcript}", transcript)

    def score_prompt(
        self, transcript: str, plan: ExamPlan, lang: str, talk_words: int
    ) -> str:
        tpl = (self.dir / "score.md").read_text(encoding="utf-8")
        tpl = tpl.replace("{explanation_language}", self._explanation_language(lang))
        tpl = tpl.replace("{cards}", _format_exam_cards(plan))
        tpl = tpl.replace("{talk_words}", str(talk_words))
        return tpl.replace("{transcript}", transcript)

    def hint_prompt(self, query: str, context: str) -> str:
        tpl = (self.dir / "hint.md").read_text(encoding="utf-8")
        values = {"context": context, "query": query}
        return re.sub(r"\{(context|query)\}", lambda match: values[match.group(1)], tpl)
