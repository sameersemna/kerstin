"""Pure scoring helpers for the post-exam rubric estimate."""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .exam import MODERATION_PREFIX, ExamPlan, is_moderation

if TYPE_CHECKING:
    from .prompts import PromptStore

CRITERIA = {
    "aufgabe": "Aufgabenerfüllung",
    "kohaerenz": "Kohärenz",
    "wortschatz": "Wortschatz",
    "grammatik": "Grammatik",
}
BANDS = {
    1: "unter B2",
    2: "B2 knapp",
    3: "B2 sicher",
    4: "über B2",
}
SCORE_NOTE = (
    "Einschätzung aus dem Transkript – keine offizielle Bewertung. "
    "Aussprache und Flüssigkeit werden nicht bewertet; die Spracherkennung "
    "kann Fehler glätten oder hinzufügen."
)


@dataclass(frozen=True)
class CriterionScore:
    key: str
    label: str
    band: int
    band_label: str
    reason: str
    evidence: str | None


@dataclass(frozen=True)
class ExamScore:
    criteria: list[CriterionScore]
    overall_band: int
    overall_label: str
    dropped_evidence: int


def learner_text(history: list[dict]) -> str:
    return "\n".join(
        str(message.get("content", ""))
        for message in history
        if message.get("role") == "user" and not is_moderation(message)
    )


def _format_transcript(history: list[dict]) -> str:
    lines = []
    for message in history:
        if is_moderation(message):
            lines.append(f"--- {message['content'][len(MODERATION_PREFIX):]} ---")
        else:
            speaker = "Lernende Person" if message.get("role") == "user" else "Kerstin"
            lines.append(f"{speaker}: {message.get('content', '')}")
    return "\n".join(lines)


def talk_word_count(history: list[dict], plan: ExamPlan) -> int:
    talk_index = next(
        (index for index, part in enumerate(plan.parts) if part.kind == "learner_talk"),
        None,
    )
    if talk_index is None:
        return 0
    target = talk_index + 1
    counting = True
    words = 0
    for message in history:
        if is_moderation(message):
            text = str(message.get("content", ""))[len(MODERATION_PREFIX):]
            match = re.search(r"\bTeil\s+(\d+)\b", text)
            if match:
                number = int(match.group(1))
                if number == target and "Rückfrage" not in text:
                    counting = True
                elif number >= target:
                    counting = False
                else:
                    counting = False
            continue
        if counting and message.get("role") == "user":
            words += len(str(message.get("content", "")).split())
    return words


def score_prompt(
    store: PromptStore, history: list[dict], plan: ExamPlan, lang: str
) -> str:
    transcript = _format_transcript(history)
    talk_words = talk_word_count(history, plan)
    return store.score_prompt(transcript, plan, lang, talk_words)


def _normalise(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _band(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        band = value
    elif isinstance(value, str) and value.strip().isdigit():
        band = int(value.strip())
    else:
        return None
    return band if 1 <= band <= 4 else None


def overall_band(bands: list[int]) -> int:
    if not bands:
        raise ValueError("overall_band needs at least one band")
    return int(statistics.median(bands))


def parse_score(raw: str, learner: str) -> ExamScore | None:
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    normalised_learner = _normalise(learner)
    criteria: list[CriterionScore] = []
    dropped = 0
    for key, label in CRITERIA.items():
        item = data.get(key)
        if not isinstance(item, dict):
            return None
        band = _band(item.get("band"))
        reason = item.get("reason")
        if band is None or not isinstance(reason, str) or not reason.strip():
            return None
        evidence = item.get("evidence")
        kept = None
        if isinstance(evidence, str):
            evidence = evidence.strip()
            normalised_evidence = _normalise(evidence)
            if normalised_evidence and normalised_evidence in normalised_learner:
                kept = evidence
        if kept is None:
            dropped += 1
        criteria.append(
            CriterionScore(
                key=key,
                label=label,
                band=band,
                band_label=BANDS[band],
                reason=reason.strip(),
                evidence=kept,
            )
        )
    bands = [criterion.band for criterion in criteria]
    return ExamScore(
        criteria=criteria,
        overall_band=overall_band(bands),
        overall_label=BANDS[overall_band(bands)],
        dropped_evidence=dropped,
    )
