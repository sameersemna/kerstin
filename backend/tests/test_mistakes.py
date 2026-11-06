"""Mistake classifier and local SQLite store tests (no network, no GPU)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from kerstin.feedback_checks import FeedbackError
from kerstin.mistakes import CATEGORIES, MistakeLog, classify, pick_focus

# Real 💡 lines copied from docs/tasks/T016-feedback-quality.md,
# docs/tasks/T011-feedback-model.md and docs/tasks/T017-feedback-language.md.
REAL_CORPUS = [
    # EN
    (
        'In German, "Meiner Meinung nach" occupies the first position, so the verb must follow immediately.',
        "verbposition",
    ),
    (
        "The preposition „mit“ always requires the dative case.",
        "kasus",
    ),
    (
        "In a subordinate clause starting with „weil“, the conjugated verb must move to the very end.",
        "verbposition",
    ),
    (
        "When expressing anticipation for a future event, the fixed preposition is „sich freuen auf“.",
        "praeposition",
    ),
    (
        "Use the accusative case because there is movement from one place to another (Wohin?).",
        "kasus",
    ),
    (
        "The preposition „mit“ always requires the dative case, which affects the adjective ending.",
        "adjektivendung",
    ),
    (
        "Verbs indicating a change of location (movement from A to B) use „sein“ as the auxiliary verb in Perfekt.",
        "perfekt_hilfsverb",
    ),
    (
        'In a subordinate clause introduced by "weil", the conjugated verb must move to the very end of the sentence.',
        "verbposition",
    ),
    (
        'The noun "Verkehr" is masculine, so the article and adjective must reflect this.',
        "genus",
    ),
    (
        'The preposition "mit" always requires the dative case, so "ein Freund" must change to "einem Freund".',
        "kasus",
    ),
    (
        'The preposition "mit" always requires the dative case, and "Chef" is masculine.',
        "kasus",
    ),
    (
        'After the preposition "in" (dative), the adjective needs a weak or mixed ending, which is "-en" here.',
        "adjektivendung",
    ),
    (
        'Movement from one place to another requires the auxiliary verb "sein" instead of "haben".',
        "perfekt_hilfsverb",
    ),
    (
        'The preposition "mit" always requires the dative case, so the plural noun needs an "-n" ending.',
        "kasus",
    ),
    # DE
    (
        "Nach der Präposition „mit“ folgt immer der Dativ (Maskulin: einem Freund).",
        "kasus",
    ),
    (
        "In einem Nebensatz mit „weil“ muss das konjugierte Verb am Ende stehen.",
        "verbposition",
    ),
    (
        "Die Präposition „auf“ benutzt man bei Ereignissen in der Zukunft (Vorfreude).",
        "praeposition",
    ),
    (
        "Nach der Präposition „mit“ folgt immer der Dativ, und das Adjektiv braucht hier die Endung „-en“.",
        "adjektivendung",
    ),
    (
        "Verben der Bewegung (von A nach B) bilden das Perfekt mit dem Hilfsverb „sein“.",
        "perfekt_hilfsverb",
    ),
    (
        "Nach der festen Wendung „Meiner Meinung nach“ muss das Verb an der zweiten Position im Satz stehen.",
        "verbposition",
    ),
    (
        "Das Nomen „Verkehr“ ist maskulin (der Verkehr), daher muss auch der Artikel und das Adjektiv im Nominativ maskulin sein.",
        "genus",
    ),
    (
        "Das Wort „mit“ verlangt den Dativ Plural, deshalb muss am Ende ein „n“ an „Fahrräder“ stehen.",
        "kasus",
    ),
    (
        "Nach der Präposition „in“ (Dativ) braucht das Adjektiv die Endung „-en“.",
        "adjektivendung",
    ),
    (
        "Das Verb „sich bedanken“ braucht die Präposition „bei“ (Person) und „für“ (Sache).",
        "praeposition",
    ),
    (
        "Das Verb „fahren“ beschreibt eine Bewegung von A nach B und bildet das Perfekt deshalb mit „sein“.",
        "perfekt_hilfsverb",
    ),
    (
        "In einem Nebensatz mit „weil“ steht das konjugierte Verb am Ende des Satzes.",
        "verbposition",
    ),
    (
        "Das Wort „Verkehr“ ist maskulin (der Verkehr), deshalb muss auch der Artikel und das Adjektiv angepasst werden.",
        "genus",
    ),
    (
        "Die Präposition „mit“ verlangt immer den Dativ, und das Adjektiv braucht hier die passende Dativ-Endung.",
        "adjektivendung",
    ),
    (
        "Nach der Präposition „mit“ benutzt man immer den Dativ.",
        "kasus",
    ),
    (
        "In einem Nebensatz mit der Konjunktion „weil“ muss das konjugierte Verb am Ende stehen.",
        "verbposition",
    ),
    (
        "Das Wort „mit“ braucht den Dativ Plural, deshalb bekommt das Nomen die Endung „-n“.",
        "kasus",
    ),
]

MADE_UP = [
    # Made-up lines for the categories the real reports did not exercise.
    ("The word choice is too informal; 'passieren' is better here.", "wortwahl"),
    ("Falsche Wortwahl: 'bekommen' passt hier nicht.", "wortwahl"),
    ("The meaning is different; use 'stellen' instead.", "wortwahl"),
    ("This is a spelling mistake, not a grammar error.", "sonstiges"),
    ("Der Satz ist unklar und passt nicht zum Kontext.", "sonstiges"),
    ("This is only a punctuation issue.", "sonstiges"),
]

CORPUS = REAL_CORPUS + MADE_UP


def _error(explanation: str) -> FeedbackError:
    return FeedbackError(quote="", correction="", explanation=explanation)


def test_classifier_corpus_is_100_percent():
    assert len(REAL_CORPUS) >= 24
    for line, expected in CORPUS:
        assert classify(_error(line)) == expected, (line, expected)


def test_categories_have_expected_labels():
    assert CATEGORIES["wortwahl"] == "Wortwahl"
    assert CATEGORIES["sonstiges"] == "Sonstiges"
    assert len(CATEGORIES) == 8


async def test_record_summary_and_order(tmp_path):
    log = MistakeLog(tmp_path / "mistakes.sqlite3")

    count = await log.record("freies_gespraech", "en", ["kasus", "verbposition", "kasus"])
    assert count == 3
    await log.record("wg_alltag", "de", ["wortwahl"])

    summary = await log.summary()
    assert summary["sessions"] == 2
    assert summary["categories"] == [
        {"key": "kasus", "label": "Kasus", "count": 2},
        {"key": "verbposition", "label": "Verbposition", "count": 1},
        {"key": "wortwahl", "label": "Wortwahl", "count": 1},
    ]


async def test_zero_categories_still_counts_a_session(tmp_path):
    log = MistakeLog(tmp_path / "mistakes.sqlite3")

    assert await log.record("freies_gespraech", "en", []) == 0
    summary = await log.summary()
    assert summary == {"sessions": 1, "categories": []}


async def test_summary_missing_file_does_not_create_it(tmp_path):
    path = tmp_path / "missing" / "mistakes.sqlite3"
    log = MistakeLog(path)

    assert await log.summary() == {"sessions": 0, "categories": []}
    assert not path.exists()
    assert not path.parent.exists()


async def test_schema_has_no_text_column(tmp_path):
    path = tmp_path / "mistakes.sqlite3"
    log = MistakeLog(path)
    await log.record("freies_gespraech", "en", ["kasus", "sonstiges"])

    conn = sqlite3.connect(path)
    try:
        session_columns = [
            row[1] for row in conn.execute("PRAGMA table_info(sessions)")
        ]
        mistake_columns = [
            row[1] for row in conn.execute("PRAGMA table_info(mistakes)")
        ]
        rows = conn.execute(
            "SELECT s.scenario, s.lang, m.category FROM sessions s "
            "JOIN mistakes m ON m.session_id = s.id ORDER BY m.category"
        ).fetchall()
    finally:
        conn.close()

    assert session_columns == ["id", "created_at", "scenario", "lang"]
    assert mistake_columns == ["session_id", "category"]
    assert "text" not in session_columns + mistake_columns
    assert rows == [
        ("freies_gespraech", "en", "kasus"),
        ("freies_gespraech", "en", "sonstiges"),
    ]


async def test_summary_days_filter(tmp_path):
    path = tmp_path / "mistakes.sqlite3"
    log = MistakeLog(path)
    await log.record("old", "en", ["kasus"])
    old_date = (datetime.now(UTC) - timedelta(days=100)).isoformat()
    conn = sqlite3.connect(path)
    try:
        with conn:
            conn.execute("UPDATE sessions SET created_at = ? WHERE id = 1", (old_date,))
    finally:
        conn.close()

    await log.record("new", "de", ["wortwahl"])
    summary = await log.summary(days=90)
    assert summary["sessions"] == 1
    assert summary["categories"] == [
        {"key": "wortwahl", "label": "Wortwahl", "count": 1}
    ]


async def test_max_days_prunes_old_rows(tmp_path):
    path = tmp_path / "mistakes.sqlite3"
    log = MistakeLog(path, max_days=30)
    await log.record("old", "en", ["kasus"])
    old_date = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    conn = sqlite3.connect(path)
    try:
        with conn:
            conn.execute("UPDATE sessions SET created_at = ? WHERE id = 1", (old_date,))
    finally:
        conn.close()

    await log.record("new", "de", ["wortwahl"])
    conn = sqlite3.connect(path)
    try:
        sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        mistakes = conn.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0]
    finally:
        conn.close()
    assert sessions == 1
    assert mistakes == 1


async def test_clear_empties_and_vacuums(tmp_path):
    path = tmp_path / "mistakes.sqlite3"
    log = MistakeLog(path)
    await log.record("freies_gespraech", "en", ["kasus", "verbposition"])

    await log.clear()

    assert await log.summary() == {"sessions": 0, "categories": []}
    assert path.exists()
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA freelist_count").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0] == 0
    finally:
        conn.close()


async def test_record_creates_parent_directory_lazily(tmp_path):
    path = tmp_path / "nested" / "mistakes.sqlite3"
    log = MistakeLog(path)

    assert await log.record("freies_gespraech", "en", ["kasus"]) == 1
    assert path.exists()
    assert path.parent.is_dir()


async def test_clear_missing_file_does_not_create_it(tmp_path):
    path = tmp_path / "missing" / "mistakes.sqlite3"
    log = MistakeLog(path)

    await log.clear()

    assert not path.exists()
    assert not path.parent.exists()


def _summary(*items: tuple[str, int]) -> dict:
    return {
        "sessions": 3,
        "categories": [
            {"key": key, "label": key, "count": count} for key, count in items
        ],
    }


def test_pick_focus_orders_by_count_and_respects_min_count():
    summary = _summary(("kasus", 2), ("verbposition", 4), ("genus", 1))

    assert pick_focus(summary, {"kasus", "verbposition", "genus"}) == [
        "verbposition",
        "kasus",
    ]
    assert pick_focus(summary, {"kasus", "verbposition", "genus"}, min_count=5) == []


def test_pick_focus_filters_available_and_caps_at_max_n():
    summary = _summary(
        ("verbposition", 5),
        ("perfekt_hilfsverb", 4),
        ("praeposition", 3),
    )

    assert pick_focus(summary, {"verbposition", "praeposition"}) == [
        "verbposition",
        "praeposition",
    ]
    assert pick_focus(
        summary, {"verbposition", "perfekt_hilfsverb", "praeposition"}, max_n=3
    ) == ["verbposition", "perfekt_hilfsverb", "praeposition"]
    assert pick_focus(summary, {"verbposition"}, max_n=0) == []


def test_pick_focus_breaks_ties_by_key():
    summary = _summary(("praeposition", 2), ("kasus", 2), ("genus", 2))

    assert pick_focus(summary, {"praeposition", "kasus", "genus"}) == [
        "genus",
        "kasus",
    ]


def test_pick_focus_handles_empty_summary_and_never_picks_text_categories():
    assert pick_focus({"sessions": 0, "categories": []}, set(CATEGORIES)) == []
    summary = _summary(("wortwahl", 10), ("sonstiges", 9), ("kasus", 2))

    assert pick_focus(summary, set(CATEGORIES)) == ["kasus"]
