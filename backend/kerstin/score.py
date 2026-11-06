"""Pure scoring helpers for the post-exam rubric estimate."""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .exam import MODERATION_PREFIX, ExamPlan, is_moderation

if TYPE_CHECKING:
    from .prompts import PromptStore

log = logging.getLogger(__name__)

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
    error_density: float
    grammar_errors: list[str]
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
    return math.floor(sum(bands) / len(bands))


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
    raw_errors = data.get("grammar_errors")
    if not isinstance(raw_errors, list):
        log.warning("score output missing or invalid grammar_errors; treating as []")
        raw_errors = []
    grammar_errors: list[str] = []
    normalised_learner_words = len(learner.split())
    for snippet in raw_errors[:15]:
        if not isinstance(snippet, str):
            dropped += 1
            continue
        snippet = snippet.strip()
        normalised_snippet = _normalise(snippet)
        if normalised_snippet and normalised_snippet in normalised_learner:
            grammar_errors.append(snippet)
        else:
            dropped += 1

    density = (
        len(grammar_errors) / normalised_learner_words * 100
        if normalised_learner_words
        else 0.0
    )
    if density >= 3.0:
        ceiling = 1
    elif density >= 1.5:
        ceiling = 2
    elif density >= 0.5:
        ceiling = 3
    else:
        ceiling = 4

    grammar_index = list(CRITERIA).index("grammatik")
    grammar = criteria[grammar_index]
    final_band = min(grammar.band, ceiling)
    grammar_evidence = grammar.evidence
    if final_band <= 3 and grammar_errors:
        grammar_evidence = grammar_errors[0]
    criteria[grammar_index] = CriterionScore(
        key=grammar.key,
        label=grammar.label,
        band=final_band,
        band_label=BANDS[final_band],
        reason=grammar.reason,
        evidence=grammar_evidence,
    )

    bands = [criterion.band for criterion in criteria]
    overall = overall_band(bands)
    return ExamScore(
        criteria=criteria,
        overall_band=overall,
        overall_label=BANDS[overall],
        error_density=round(density, 1),
        grammar_errors=grammar_errors,
        dropped_evidence=dropped,
    )
