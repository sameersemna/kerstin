"""Incremental sentence splitting for streaming LLM output into TTS.

The LLM streams tokens; we want to hand complete sentences to TTS as early
as possible without cutting German abbreviations ("z. B.", "usw.") or
ordinals ("am 3. Mai") in half.
"""

from __future__ import annotations

import re

# Lower-cased abbreviations that end with a period but do not end a sentence.
ABBREVIATIONS = {
    "z.b", "b", "z", "bzw", "usw", "etc", "ca", "dr", "prof", "nr", "str",
    "evtl", "ggf", "inkl", "vgl", "u.a", "d.h", "h", "u", "a", "s", "o.ä",
    "mio", "mrd", "jh", "jhd", "bspw", "sog", "hr", "fr", "tel", "abs",
}

_END_CHARS = ".!?…"
_CLOSERS = "\"'»«)”“’"

MIN_SENTENCE_CHARS = 12  # avoid tiny fragments like "Ja." being synthesized alone... unless flushed


def _last_word(text: str) -> str:
    m = re.search(r"([\wÄÖÜäöüß.]+)\.$", text)
    return m.group(1).lower().rstrip(".") if m else ""


def _is_boundary(buf: str, i: int) -> bool:
    """Is buf[i] (an end char) a real sentence end, given buf[i+1] is whitespace?"""
    ch = buf[i]
    if ch in "!?…":
        return True
    # ch == "."
    head = buf[: i + 1]
    word = _last_word(head)
    if word in ABBREVIATIONS:
        return False
    # Ordinal / number like "3." or "2024." followed by a lowercase or digit-ish continuation
    if re.search(r"\b\d{1,4}\.$", head):
        nxt = buf[i + 1 :].lstrip()[:1]
        if nxt and (nxt.islower() or nxt.isdigit() or nxt in "JFMASOND"):  # months often follow
            return False
    # Ellipsis written as "..."
    if head.endswith(".."):
        return True
    return True


class SentenceSplitter:
    """Feed text chunks with .feed(); it returns any complete sentences.

    Call .flush() at the end of the stream to get the remainder.
    """

    def __init__(
        self,
        min_chars: int = MIN_SENTENCE_CHARS,
        first_clause_min_words: int = 0,
    ) -> None:
        self.buf = ""
        self.min_chars = min_chars
        self.first_clause_min_words = first_clause_min_words
        self._emitted = False

    def _is_clause_boundary(self, i: int, start: int) -> bool:
        ch = self.buf[i]
        if ch in ",;:":
            if (
                ch == ","
                and i > 0
                and i + 1 < len(self.buf)
                and self.buf[i - 1].isdigit()
                and self.buf[i + 1].isdigit()
            ):
                return False
            return i + 1 < len(self.buf) and self.buf[i + 1].isspace()
        if ch in "–-":
            return (
                i > start
                and self.buf[i - 1].isspace()
                and i + 1 < len(self.buf)
                and self.buf[i + 1].isspace()
            )
        return False

    def feed(self, chunk: str) -> list[str]:
        self.buf += chunk
        out: list[str] = []
        start = 0
        i = 0
        while i < len(self.buf) - 1:
            ch = self.buf[i]
            if ch in _END_CHARS:
                j = i
                # include closing quotes/brackets right after the end char
                while j + 1 < len(self.buf) and self.buf[j + 1] in _CLOSERS:
                    j += 1
                if j + 1 < len(self.buf) and self.buf[j + 1].isspace() and _is_boundary(self.buf, i):
                    candidate = self.buf[start : j + 1].strip()
                    if len(candidate) >= self.min_chars:
                        out.append(candidate)
                        start = j + 1
                        self._emitted = True
                    i = j
            elif ch == "\n" and self.buf[start:i].strip():
                candidate = self.buf[start:i].strip()
                if len(candidate) >= self.min_chars:
                    out.append(candidate)
                    start = i + 1
                    self._emitted = True
            elif (
                self.first_clause_min_words > 0
                and not self._emitted
                and self._is_clause_boundary(i, start)
            ):
                before = self.buf[start:i].strip()
                if len(before.split()) >= self.first_clause_min_words:
                    out.append(self.buf[start : i + 1].strip())
                    start = i + 1
                    self._emitted = True
            i += 1
        self.buf = self.buf[start:]
        return out

    def flush(self) -> list[str]:
        rest = self.buf.strip()
        self.buf = ""
        if rest:
            self._emitted = True
        return [rest] if rest else []


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think(text: str) -> str:
    """Remove <think>...</think> blocks some models emit even with thinking off."""
    return _THINK_RE.sub("", text)


def clean_for_tts(text: str) -> str:
    """Remove markdown and symbols that TTS would read aloud."""
    text = strip_think(text)
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
