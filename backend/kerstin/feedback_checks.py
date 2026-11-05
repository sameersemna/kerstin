"""Pure checks for structured end-of-session feedback."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

HEADINGS = (
    "Was gut war",
    "Wichtigste Fehler",
    "Besser ausdrücken",
    "Tipp für das nächste Gespräch",
)
HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*$")
LABEL_RE = re.compile(
    r"^\s*(?:Original|Korrektur|Erklärung|Explanation)\s*:\s*", re.IGNORECASE
)
QUOTE_PATTERNS = (
    re.compile(r"„([^“]+)“"),
    re.compile(r"“([^”]+)”"),
    re.compile(r'"([^"]+)"'),
)
PUNCT_RE = re.compile(r"[^\w]+", re.UNICODE)
EN_STOPWORDS = ("the", "is", "with", "of", "to", "because", "uses", "and", "for", "that", "this")
DE_STOPWORDS = ("der", "die", "das", "ist", "mit", "weil", "wird")


@dataclass(frozen=True)
class FeedbackError:
    quote: str
    correction: str
    explanation: str


@dataclass(frozen=True)
class FeedbackCheck:
    structure_ok: bool
    ungrounded: int
    quotes_kerstin: int
    false_corrections: int
    noop_corrections: int
    format_noise: int
    lang_mismatch: bool
    errors: tuple[FeedbackError, ...]


def normalize(text: str) -> str:
    cleaned = text.lower().replace("*", "").replace("_", "").replace("`", "")
    return " ".join(PUNCT_RE.sub(" ", cleaned).split())


def best_window_ratio(quote: str, text: str) -> float:
    quote_norm = normalize(quote)
    text_norm = normalize(text)
    if not quote_norm or not text_norm:
        return 0.0
    if quote_norm in text_norm:
        return 1.0

    quote_words = quote_norm.split()
    text_words = text_norm.split()
    best = 0.0
    for start in range(len(text_words)):
        for end in range(start + 1, len(text_words) + 1):
            ratio = SequenceMatcher(None, quote_words, text_words[start:end]).ratio()
            best = max(best, ratio)
            if best >= 0.8:
                return best
    return best


def _after_marker(line: str, marker: str) -> str:
    index = line.find(marker)
    if index == -1:
        return ""
    return line[index + len(marker) :].strip()


def _extract_text(line: str, marker: str, prefer_quote: bool = True) -> str:
    content = _after_marker(line, marker)
    if prefer_quote:
        for pattern in QUOTE_PATTERNS:
            match = pattern.search(content)
            if match:
                return match.group(1).strip()
    content = content.strip(" \t*_")
    return LABEL_RE.sub("", content).strip(" \t*_")


def parse_errors(markdown: str) -> tuple[FeedbackError, ...]:
    lines = markdown.splitlines()
    error_indices = [index for index, line in enumerate(lines) if "❌" in line]
    errors: list[FeedbackError] = []
    for position, index in enumerate(error_indices):
        end = error_indices[position + 1] if position + 1 < len(error_indices) else len(lines)
        corrections = []
        explanations = []
        for line in lines[index + 1 : end]:
            if "✅" in line:
                corrections.append(_extract_text(line, "✅"))
            if "💡" in line:
                explanations.append(_extract_text(line, "💡", prefer_quote=False))
        errors.append(
            FeedbackError(
                quote=_extract_text(lines[index], "❌"),
                correction=" ".join(part for part in corrections if part),
                explanation=" ".join(part for part in explanations if part),
            )
        )
    return tuple(errors)


def check_structure(markdown: str) -> bool:
    lines = markdown.splitlines()
    previous = -1
    for title in HEADINGS:
        found = -1
        for index, line in enumerate(lines):
            match = HEADING_RE.match(line.strip())
            if match and match.group(1).strip() == title:
                found = index
                break
        if found <= previous:
            return False
        previous = found

    error_indices = [index for index, line in enumerate(lines) if "❌" in line]
    if sum(line.count("❌") for line in lines) > 5:
        return False
    for position, index in enumerate(error_indices):
        end = error_indices[position + 1] if position + 1 < len(error_indices) else len(lines)
        section = lines[index + 1 : end]
        if not any("✅" in line for line in section):
            return False
        if not any("💡" in line for line in section):
            return False
    return True


def check_quote_grounding(
    errors: tuple[FeedbackError, ...], messages: list[dict]
) -> tuple[int, int]:
    learner_lines = [message["content"] for message in messages if message["role"] == "user"]
    kerstin_lines = [
        message["content"] for message in messages if message["role"] == "assistant"
    ]

    ungrounded = 0
    quotes_kerstin = 0
    for error in errors:
        learner_best = max(
            (best_window_ratio(error.quote, line) for line in learner_lines),
            default=0.0,
        )
        kerstin_best = max(
            (best_window_ratio(error.quote, line) for line in kerstin_lines),
            default=0.0,
        )
        if learner_best < 0.8:
            ungrounded += 1
        if kerstin_best >= 0.8:
            quotes_kerstin += 1
    return ungrounded, quotes_kerstin


PlantedOutcome = Literal["found", "wrong_correction", "missed"]


def _contains_words(haystack: list[str], needle: list[str]) -> bool:
    if not needle:
        return False
    width = len(needle)
    return any(haystack[index : index + width] == needle for index in range(len(haystack)))


def _contains_in_order(needle: list[str], haystack: list[str]) -> bool:
    position = 0
    for word in haystack:
        if position < len(needle) and word == needle[position]:
            position += 1
    return position == len(needle)


def check_planted(
    errors: tuple[FeedbackError, ...], planted: list[dict]
) -> list[PlantedOutcome]:
    outcomes: list[PlantedOutcome] = []
    for item in planted:
        wrong_words = normalize(item.get("wrong", "")).split()
        right_words = normalize(item.get("right", "")).split()
        if not wrong_words or not right_words:
            outcomes.append("missed")
            continue

        matching = [
            error
            for error in errors
            if _contains_words(normalize(error.quote).split(), wrong_words)
        ]
        if not matching:
            outcomes.append("missed")
            continue

        found = any(
            not _contains_words(normalize(error.correction).split(), wrong_words)
            and _contains_in_order(right_words, normalize(error.correction).split())
            for error in matching
        )
        outcomes.append("found" if found else "wrong_correction")
    return outcomes


def count_false_corrections(
    errors: tuple[FeedbackError, ...], correct_tricky: list[str]
) -> int:
    return sum(
        1
        for error in errors
        if any(best_window_ratio(error.quote, line) >= 0.8 for line in correct_tricky)
    )


def count_noop_corrections(errors: tuple[FeedbackError, ...]) -> int:
    return sum(
        1
        for error in errors
        if normalize(error.quote) and normalize(error.quote) == normalize(error.correction)
    )


def count_format_noise(markdown: str) -> int:
    count = len(re.findall(r"\$[^$\n]+\$", markdown))
    count += markdown.count("\\rightarrow")
    count += len(re.findall(r"<[^>\n]+>", markdown))
    count += len(re.findall(r"\|[ \t]*:?-{3,}", markdown))
    return count


def explanation_language_ok(text: str, lang: str) -> bool:
    lowered = text.lower()
    english = sum(len(re.findall(rf"\b{word}\b", lowered)) for word in EN_STOPWORDS)
    german = sum(len(re.findall(rf"\b{word}\b", lowered)) for word in DE_STOPWORDS)
    if lang == "en":
        return english > german
    if lang == "de":
        return german > english
    return False


def has_language_mismatch(markdown: str, lang: str) -> bool:
    explanations = [
        _extract_text(line, "💡", prefer_quote=False)
        for line in markdown.splitlines()
        if "💡" in line and _extract_text(line, "💡", prefer_quote=False)
    ]
    return any(not explanation_language_ok(text, lang) for text in explanations)


def check_feedback(
    markdown: str, messages: list[dict], correct_tricky: list[str], lang: str
) -> FeedbackCheck:
    errors = parse_errors(markdown)
    ungrounded, quotes_kerstin = check_quote_grounding(errors, messages)
    return FeedbackCheck(
        structure_ok=check_structure(markdown),
        ungrounded=ungrounded,
        quotes_kerstin=quotes_kerstin,
        false_corrections=count_false_corrections(errors, correct_tricky),
        noop_corrections=count_noop_corrections(errors),
        format_noise=count_format_noise(markdown),
        lang_mismatch=has_language_mismatch(markdown, lang),
        errors=errors,
    )
