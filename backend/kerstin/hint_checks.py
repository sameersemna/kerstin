"""Pure checks for the typed hint answers (hold-out eval)."""

from __future__ import annotations

import re
from dataclasses import dataclass

BOLD_RE = re.compile(r"^\s*\*\*(.+?)\*\*")
QUOTE_RE = re.compile(r"„[^“]*“|“[^”]*”|\"[^\"]*\"")
PAREN_RE = re.compile(r"\(([^)]*)\)")
WORD_RE = re.compile(r"\w+", re.UNICODE)
ARTICLE_RE = re.compile(r"^(der|die|das)\b", re.IGNORECASE)
PLURAL_RE = re.compile(r"\bPl\.|\bnur Sg\.", re.IGNORECASE)
VERB_FORM_RE = re.compile(r"\b(ist|war|hat)\b", re.IGNORECASE)
CASE_RE = re.compile(r"\s*\+\s*(Akk|Dat)\.?.*$", re.IGNORECASE)
STOPWORDS = {
    "der",
    "die",
    "das",
    "den",
    "dem",
    "des",
    "ein",
    "eine",
    "einen",
    "einem",
    "einer",
    "eines",
    "sich",
    "jemanden",
    "jemandem",
    "etwas",
    "man",
    "sein",
    "nur",
    "sg",
    "pl",
    "akk",
    "dat",
    "an",
    "auf",
    "aus",
    "bei",
    "für",
    "gegen",
    "in",
    "mit",
    "nach",
    "über",
    "um",
    "unter",
    "von",
    "vor",
    "zu",
    "zwischen",
}
PREFIXES = (
    "ab",
    "an",
    "auf",
    "aus",
    "bei",
    "ein",
    "fest",
    "her",
    "hin",
    "los",
    "mit",
    "nach",
    "vor",
    "weg",
    "zu",
    "zurück",
    "zusammen",
)


@dataclass(frozen=True)
class HintCheck:
    format_ok: bool
    lemma_ok: bool
    pos_ok: bool
    example_ok: bool
    format_noise: int
    lemma: str
    example: str
    lines: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return (
            self.format_ok
            and self.lemma_ok
            and self.pos_ok
            and self.example_ok
            and self.format_noise == 0
        )


def normalize(text: str) -> str:
    cleaned = text.lower().replace("*", "").replace("_", "").replace("`", "")
    return " ".join(WORD_RE.findall(cleaned))


def _clean_lemma(bold: str) -> str:
    bold = re.sub(r"\s*\([^)]*\)", "", bold)
    return CASE_RE.sub("", bold).strip()


def _extract_lemma(lines: tuple[str, ...]) -> str:
    if not lines:
        return ""
    match = BOLD_RE.search(lines[0])
    return _clean_lemma(match.group(1).strip()) if match else ""


def _extract_example(lines: tuple[str, ...]) -> str:
    if not lines:
        return ""
    line = lines[-1]
    if not line.startswith("Beispiel:"):
        return ""
    quotes = QUOTE_RE.findall(line)
    return quotes[0] if len(quotes) == 1 else ""


def _format_noise(answer: str) -> int:
    noise = len(re.findall(r"\$[^$\n]+\$", answer))
    noise += answer.count("\\rightarrow")
    noise += len(re.findall(r"\|[ \t]*:?-{3,}", answer))
    return noise


def _format_ok(lines: tuple[str, ...]) -> bool:
    if len(lines) not in (2, 3):
        return False
    if not BOLD_RE.search(lines[0]):
        return False
    if not lines[-1].startswith("Beispiel:"):
        return False
    return len(QUOTE_RE.findall(lines[-1])) == 1


def _noun_ok(lines: tuple[str, ...], lemma: str) -> bool:
    return bool(
        lines
        and ARTICLE_RE.match(lemma)
        and PLURAL_RE.search(lines[0])
    )


def _adj_ok(lines: tuple[str, ...]) -> bool:
    if not lines:
        return False
    return not any(
        VERB_FORM_RE.search(content) for content in PAREN_RE.findall(lines[0])
    )


def _strip_infinitive(word: str) -> str:
    for suffix in ("en", "ern", "eln", "n"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _stem_forms(word: str) -> set[str]:
    forms = {word, _strip_infinitive(word)}
    for prefix in PREFIXES:
        if word.startswith(prefix) and len(word) > len(prefix) + 2:
            rest = word[len(prefix) :]
            forms.add(rest)
            forms.add(_strip_infinitive(rest))
    return {form for form in forms if len(form) >= 3}


def _content_words(lemma: str) -> list[str]:
    return [
        word
        for word in normalize(lemma).split()
        if word not in STOPWORDS and len(word) >= 3
    ]


def _example_ok(example: str, lemma: str) -> bool:
    if not example:
        return False
    tokens = normalize(example).split()
    for word in _content_words(lemma):
        forms = _stem_forms(word)
        if not any(token.startswith(form) for token in tokens for form in forms):
            return False
    return True


def check_hint(answer: str, case: dict) -> HintCheck:
    lines = tuple(line.strip() for line in answer.splitlines() if line.strip())
    lemma = _extract_lemma(lines)
    example = _extract_example(lines)
    lemma_norm = normalize(lemma)
    accepts = {normalize(value) for value in case.get("accept", [])}
    pos = case.get("pos", "verb")

    format_ok = _format_ok(lines)
    lemma_ok = bool(lemma_norm) and lemma_norm in accepts
    if pos == "noun":
        pos_ok = _noun_ok(lines, lemma)
    elif pos == "adj":
        pos_ok = _adj_ok(lines)
    else:
        pos_ok = True
    example_ok = _example_ok(example, lemma)

    return HintCheck(
        format_ok=format_ok,
        lemma_ok=lemma_ok,
        pos_ok=pos_ok,
        example_ok=example_ok,
        format_noise=_format_noise(answer),
        lemma=lemma,
        example=example,
        lines=lines,
    )
