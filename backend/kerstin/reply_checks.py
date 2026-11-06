"""Pure reply checks for the persona contract (no I/O)."""

from __future__ import annotations

import re
import unicodedata

from .text import SentenceSplitter

# Short list of common English words. One hit (e.g. "okay") is tolerated;
# two or more hits flag the reply as English.
ENGLISH_WORDS = frozenset(
    {"the", "and", "you", "is", "are", "what", "really", "okay", "cool", "nice"}
)

CORRECTION_PHRASES = (
    "man sagt",
    "richtig heißt",
    "richtig wäre",
    "du meinst wohl",
    "kleiner tipp",
    "korrekt ist",
    "es heißt nicht",
)

_ENGLISH_TOKEN_RE = re.compile(r"[a-z]+")
_MAN_SAGT_CUES = ("nicht", "statt", "richtig", "falsch", "besser", "eher", "korrekt")
_META_TALK_RE = re.compile(
    r"\b(fokus|schwerpunkt|grammatik|fehler|üben|übung|korrigier\w*|"
    r"impuls\w*|verbposition|nebensatz)\b",
    re.IGNORECASE,
)


def count_sentences(text: str) -> int:
    splitter = SentenceSplitter(min_chars=0)
    return len(splitter.feed(text) + splitter.flush())


def _has_markdown_or_emoji(text: str) -> bool:
    if "*" in text or "#" in text or "`" in text:
        return True
    if re.search(r"(?m)^\s*-\s", text):
        return True
    return any(unicodedata.category(ch) == "So" for ch in text)


def _english_hits(text: str) -> int:
    return sum(1 for token in _ENGLISH_TOKEN_RE.findall(text.lower()) if token in ENGLISH_WORDS)


def _has_correction(text: str) -> bool:
    lowered = text.lower()
    for phrase in CORRECTION_PHRASES:
        if phrase != "man sagt":
            if phrase in lowered:
                return True
            continue
        # "Man sagt zum Beispiel ..." is often a translation, not a correction.
        start = 0
        while (index := lowered.find(phrase, start)) >= 0:
            window = lowered[index : index + 60]
            if any(cue in window for cue in _MAN_SAGT_CUES):
                return True
            start = index + 1
    return False


def has_meta_talk(text: str) -> bool:
    return bool(_META_TALK_RE.search(text))


def check_reply(text: str) -> list[str]:
    """Return violation codes for one full Kerstin reply."""
    codes: list[str] = []
    if count_sentences(text) > 3:
        codes.append("too_long")
    if "?" not in text:
        codes.append("no_question")
    if _has_markdown_or_emoji(text):
        codes.append("markdown_or_emoji")
    if re.search(r"[0-9]", text):
        codes.append("digits")
    if _english_hits(text) >= 2:
        codes.append("english")
    if _has_correction(text):
        codes.append("correction")
    if has_meta_talk(text):
        codes.append("meta_talk")
    return codes
