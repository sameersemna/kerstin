"""Opt-in local mistake log: grammar categories only, never learner text."""

from __future__ import annotations

import asyncio
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .feedback_checks import FeedbackError

CATEGORIES: dict[str, str] = {
    "verbposition": "Verbposition",
    "kasus": "Kasus",
    "praeposition": "Präpositionen",
    "adjektivendung": "Adjektivendungen",
    "perfekt_hilfsverb": "Perfekt mit sein/haben",
    "genus": "Genus (Artikel)",
    "wortwahl": "Wortwahl",
    "sonstiges": "Sonstiges",
}


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def classify(error: FeedbackError) -> str:
    """Classify one feedback item from its explanation, first match wins."""
    text = (error.explanation or f"{error.quote} {error.correction}").lower()

    if _has(text, r"\b(perfect|perfekt|auxiliary|hilfsverb)\b") and _has(
        text, r"\b(sein|haben|movement|bewegung)\b"
    ):
        return "perfekt_hilfsverb"
    sentence_end = _has(text, r"\bam ende\b") and _has(
        text, r"\b(satz|verb|nebensatz|clause)\b"
    )
    if sentence_end or _has(
        text,
        r"\bword order\b",
        r"\bwortstellung\b",
        r"\bverb position\b",
        r"\bverbposition\b",
        r"\bsubordinate\b",
        r"\bnebensatz\b",
        r"\bend of the (sentence|clause)\b",
        r"\bsecond position\b",
        r"\bzweite(?:n)? position\b",
        r"\bposition 2\b",
    ):
        return "verbposition"
    if _has(text, r"\b(adjective|adjektiv)\b") and _has(
        text, r"\b(ending|endung)\b"
    ):
        return "adjektivendung"
    if _has(
        text,
        r"\b(dative|dativ|accusative|akkusativ|genitive|genitiv|case|kasus)\b",
    ):
        return "kasus"
    if _has(
        text,
        r"\b(masculine|feminine|neuter|maskulin|feminin|neutrum|gender|genus)\b",
    ):
        return "genus"
    if _has(text, r"\b(preposition|präposition)\b"):
        return "praeposition"
    if _has(
        text,
        r"\bword choice\b",
        r"\bwortwahl\b",
        r"\bwrong word\b",
        r"\bfalsches wort\b",
        r"\bidiomatic\b",
        r"\bidiomatisch\b",
        r"\bmeaning\b",
        r"\bbedeutung\b",
    ):
        return "wortwahl"
    return "sonstiges"


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.isoformat()


class MistakeLog:
    def __init__(self, path: Path, max_days: int = 180) -> None:
        self.path = Path(path)
        self.max_days = max_days

    async def record(self, scenario: str, lang: str, categories: list[str]) -> int:
        return await asyncio.to_thread(self._record, scenario, lang, categories)

    async def summary(self, days: int = 90) -> dict:
        if not self.path.exists():
            return {"sessions": 0, "categories": []}
        return await asyncio.to_thread(self._summary, days)

    async def clear(self) -> None:
        if not self.path.exists():
            return
        await asyncio.to_thread(self._clear)

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL,
                scenario TEXT NOT NULL,
                lang TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mistakes (
                session_id INTEGER NOT NULL
                    REFERENCES sessions(id) ON DELETE CASCADE,
                category TEXT NOT NULL
            )
            """
        )

    def _record(self, scenario: str, lang: str, categories: list[str]) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        now = _utc_now()
        cutoff = _iso(now - timedelta(days=self.max_days))
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            self._ensure_schema(conn)
            with conn:
                cursor = conn.execute(
                    "INSERT INTO sessions (created_at, scenario, lang) VALUES (?, ?, ?)",
                    (_iso(now), scenario, lang),
                )
                session_id = cursor.lastrowid
                conn.executemany(
                    "INSERT INTO mistakes (session_id, category) VALUES (?, ?)",
                    [(session_id, category) for category in categories],
                )
                conn.execute(
                    "DELETE FROM sessions WHERE created_at < ?",
                    (cutoff,),
                )
        finally:
            conn.close()
        return len(categories)

    def _summary(self, days: int) -> dict:
        cutoff = _iso(_utc_now() - timedelta(days=days))
        try:
            conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            return {"sessions": 0, "categories": []}
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if "sessions" not in tables or "mistakes" not in tables:
                return {"sessions": 0, "categories": []}
            sessions = conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE created_at >= ?",
                (cutoff,),
            ).fetchone()[0]
            rows = conn.execute(
                """
                SELECT m.category, COUNT(*)
                FROM mistakes AS m
                JOIN sessions AS s ON s.id = m.session_id
                WHERE s.created_at >= ?
                GROUP BY m.category
                ORDER BY COUNT(*) DESC, m.category ASC
                """,
                (cutoff,),
            ).fetchall()
        finally:
            conn.close()
        return {
            "sessions": int(sessions),
            "categories": [
                {"key": key, "label": CATEGORIES.get(key, key), "count": int(count)}
                for key, count in rows
            ],
        }

    def _clear(self) -> None:
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if "sessions" not in tables:
                return
            with conn:
                conn.execute("DELETE FROM sessions")
            conn.execute("VACUUM")
        finally:
            conn.close()
