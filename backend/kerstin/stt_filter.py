"""Pure transcript cleanup for Whisper hallucinations, tags and repetition."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# Extend these lists from real observations.
TAG_WORDS = frozenset(
    {
        "musik",
        "applaus",
        "lachen",
        "blank_audio",
        "stille",
        "geräusche",
        "music",
        "silence",
    }
)
TAG_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*")
TAG_TOKEN_RE = re.compile(r"[a-zäöüß_]+")

# Extend these lists from real observations. Both are matched on the
# normalized text (lowercase, punctuation replaced by spaces).
HALLUCINATION_SUBSTRINGS = (
    "amara org",
    "untertitel im auftrag",
    "untertitelung des zdf",
    "untertitelung im auftrag",
    "copyright wdr",
    "swr 20",
    "zdf für funk",
    "www",
)
HALLUCINATION_UTTERANCES = frozenset(
    {
        "vielen dank fürs zuschauen",
        "danke fürs zuschauen",
        "bis zum nächsten mal",
        "tschüss",
        "untertitel",
        "vielen dank",
        "amen",
    }
)

_PUNCT_RE = re.compile(r"[^\w]+", re.UNICODE)


def _normalize(text: str) -> str:
    return " ".join(_PUNCT_RE.sub(" ", text.lower()).split())


def _is_tag_only(inner: str) -> bool:
    tokens = TAG_TOKEN_RE.findall(inner.lower())
    return bool(tokens) and all(token in TAG_WORDS for token in tokens)


def _strip_tags(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        inner = match.group(0)[1:-1]
        return "" if _is_tag_only(inner) else match.group(0)

    return " ".join(TAG_RE.sub(replace, text).split()).strip()


def _trim_repetitions(text: str) -> str:
    words = text.split()
    if not words:
        return text

    while True:
        trimmed = False
        keys = [_normalize(word) for word in words]
        for n in range(4, 0, -1):
            i = 0
            while i + n <= len(words):
                block = keys[i : i + n]
                if not all(block):
                    i += 1
                    continue
                count = 1
                j = i + n
                while j + n <= len(words) and keys[j : j + n] == block:
                    count += 1
                    j += n
                if count >= 4:
                    del words[i + n : j]
                    del keys[i + n : j]
                    trimmed = True
                    i += n
                else:
                    i += 1
        if not trimmed:
            break

    return " ".join(words)


def is_echo(
    transcript: str, last_reply: str, min_words: int = 4, threshold: float = 0.7
) -> bool:
    """Return True when a transcript is mostly Kerstin's own last reply."""
    transcript_words = _normalize(transcript).split()
    reply_words = _normalize(last_reply).split()
    if len(transcript_words) < min_words or not reply_words:
        return False

    if SequenceMatcher(None, transcript_words, reply_words).ratio() >= threshold:
        return True

    for start in range(len(transcript_words) - min_words + 1):
        needle = transcript_words[start : start + min_words]
        for reply_start in range(len(reply_words) - min_words + 1):
            if reply_words[reply_start : reply_start + min_words] == needle:
                return True
    return False


def clean_transcript(text: str) -> tuple[str, str | None]:
    """Return (cleaned text, reason); reason is None when the text is kept."""
    if not text or not text.strip():
        return "", "empty"

    stripped = _strip_tags(text)
    if not stripped:
        return "", "tags_only"

    normalized = _normalize(stripped)
    if not normalized:
        return "", "empty"
    if any(marker in normalized for marker in HALLUCINATION_SUBSTRINGS):
        return "", "hallucination"
    if normalized in HALLUCINATION_UTTERANCES:
        return "", "hallucination"

    trimmed = _trim_repetitions(stripped)
    if trimmed != stripped:
        return trimmed, "repetition_trimmed"
    return stripped, None
