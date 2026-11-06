"""Pure tests for the exam scoring helpers and prompt hold-out."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from kerstin.config import BACKEND_DIR
from kerstin.exam import MODERATION_PREFIX, load_presets, make_plan
from kerstin.score import (
    CRITERIA,
    learner_text,
    overall_band,
    parse_score,
    talk_word_count,
)

ROOT = Path(__file__).resolve().parents[2]
SCORE_CASES = ROOT / "scripts" / "score_cases.json"
SCORE_PROMPT = BACKEND_DIR / "prompts" / "score.md"
LEARNER = (
    "Ich wohne seit zwei Jahren in Berlin. "
    "Ich finde die Stadt gut, weil ich kurze Wege habe."
)


def payload(**overrides):
    values = {
        "aufgabe": {
            "band": 2,
            "reason": "Die Aufgabe ist teilweise erfüllt.",
            "evidence": "Ich wohne seit zwei Jahren",
        },
        "kohaerenz": {
            "band": 3,
            "reason": "Die Aussagen sind verbunden.",
            "evidence": "weil ich kurze Wege habe",
        },
        "wortschatz": {
            "band": 3,
            "reason": "Der Wortschatz passt.",
            "evidence": "Ich finde die Stadt gut",
        },
        "grammatik": {
            "band": 4,
            "reason": "Die Strukturen sind sicher.",
            "evidence": "Ich wohne seit zwei Jahren in Berlin",
        },
        "grammar_errors": [],
    }
    values.update(overrides)
    return values


def test_parse_score_valid_and_band_string():
    data = payload(kohaerenz={**payload()["kohaerenz"], "band": "3"})
    score = parse_score(json.dumps(data), LEARNER)
    assert score is not None
    assert [criterion.key for criterion in score.criteria] == list(CRITERIA)
    assert [criterion.band for criterion in score.criteria] == [2, 3, 3, 4]
    assert [criterion.label for criterion in score.criteria] == list(CRITERIA.values())
    assert score.overall_band == 3
    assert score.overall_label == "B2 sicher"
    assert score.dropped_evidence == 0
    assert score.criteria[0].evidence == "Ich wohne seit zwei Jahren"


def test_parse_score_missing_key_rejected():
    data = payload()
    del data["grammatik"]
    assert parse_score(json.dumps(data), LEARNER) is None


def test_parse_score_out_of_range_bands_rejected():
    for band in (0, 5):
        data = payload(aufgabe={**payload()["aufgabe"], "band": band})
        assert parse_score(json.dumps(data), LEARNER) is None


def test_parse_score_fabricated_evidence_is_dropped():
    data = payload(
        aufgabe={
            **payload()["aufgabe"],
            "evidence": "Ich habe nie in Berlin gewohnt",
        }
    )
    score = parse_score(json.dumps(data), LEARNER)
    assert score is not None
    assert score.criteria[0].evidence is None
    assert score.dropped_evidence == 1


def test_parse_score_evidence_is_case_and_punctuation_insensitive():
    learner = "Ich wohne in Berlin!"
    data = payload(
        aufgabe={**payload()["aufgabe"], "evidence": "ich wohne in berlin"},
        kohaerenz={**payload()["kohaerenz"], "evidence": "ICH WOHNE IN BERLIN"},
        wortschatz={**payload()["wortschatz"], "evidence": "wohne in berlin"},
        grammatik={**payload()["grammatik"], "evidence": "Ich wohne in Berlin!"},
    )
    score = parse_score(json.dumps(data), learner)
    assert score is not None
    assert score.dropped_evidence == 0
    assert all(criterion.evidence is not None for criterion in score.criteria)


def test_overall_band_is_floor_of_mean():
    assert overall_band([1, 2, 3, 4]) == 2
    assert overall_band([1, 1, 4, 4]) == 2
    assert overall_band([2, 3, 3, 4]) == 3
    assert overall_band([3, 4, 4, 4]) == 3


def test_learner_text_excludes_kerstin_and_markers():
    history = [
        {"role": "assistant", "content": "Hallo."},
        {"role": "user", "content": "Ich wohne in Berlin."},
        {"role": "user", "content": f"{MODERATION_PREFIX}Teil 2 – Rückfrage"},
        {"role": "assistant", "content": "Wirklich?"},
        {"role": "user", "content": "Ja, seit zwei Jahren."},
    ]
    assert learner_text(history) == "Ich wohne in Berlin.\nJa, seit zwei Jahren."


def test_talk_word_count_uses_the_talk_part():
    plan = make_plan("vortrag_diskussion", load_presets(BACKEND_DIR / "prompts"), 1)
    history = [
        {"role": "user", "content": f"{MODERATION_PREFIX}Teil 2 – Dein Kurzvortrag"},
        {"role": "user", "content": "Das ist ein kurzer Vortrag mit acht Wörtern."},
        {"role": "user", "content": f"{MODERATION_PREFIX}Teil 4 – Diskussion"},
        {"role": "user", "content": "Diese Wörter gehören nicht mehr zum Vortrag."},
    ]
    assert talk_word_count(history, plan) == 8


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _normalise(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^\w\s]", "", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def test_score_prompt_has_no_six_word_sequence_from_holdout_cases():
    cases = json.loads(SCORE_CASES.read_text(encoding="utf-8"))
    prompt = _normalise(SCORE_PROMPT.read_text(encoding="utf-8"))
    sequences = set()
    for value in _strings(cases):
        words = _normalise(value).split()
        for index in range(len(words) - 5):
            sequences.add(" ".join(words[index : index + 6]))
    hits = [sequence for sequence in sequences if f" {sequence} " in f" {prompt} "]
    assert not hits, f"hold-out sequences leaked into score.md: {hits[:3]}"


def _density_score(learner: str, errors: list[str], grammar_band: int = 4):
    data = payload(
        grammatik={
            **payload()["grammatik"],
            "band": grammar_band,
            "evidence": "fehler eins",
        },
        grammar_errors=errors,
    )
    return parse_score(json.dumps(data), learner)


def test_grammar_density_ceiling_thresholds():
    words_100 = ["fehler eins", "fehler zwei", "fehler drei"] + ["wort"] * 94
    words_200 = ["fehler eins", "fehler zwei", "fehler drei"] + ["wort"] * 194
    words_200_one = ["fehler eins"] + ["wort"] * 198

    score = _density_score(" ".join(words_100), ["fehler eins", "fehler zwei", "fehler drei"])
    assert score is not None
    assert score.error_density == 3.0
    assert score.criteria[-1].band == 1

    score = _density_score(" ".join(words_100), ["fehler eins", "fehler zwei"])
    assert score is not None
    assert score.error_density == 2.0
    assert score.criteria[-1].band == 2

    score = _density_score(" ".join(words_200), ["fehler eins", "fehler zwei", "fehler drei"])
    assert score is not None
    assert score.error_density == 1.5
    assert score.criteria[-1].band == 2

    score = _density_score(" ".join(words_100), ["fehler eins"])
    assert score is not None
    assert score.error_density == 1.0
    assert score.criteria[-1].band == 3

    score = _density_score(" ".join(words_200_one), ["fehler eins"])
    assert score is not None
    assert score.error_density == 0.5
    assert score.criteria[-1].band == 3

    score = _density_score(" ".join(words_100), [])
    assert score is not None
    assert score.error_density == 0.0
    assert score.criteria[-1].band == 4


def test_unverified_grammar_snippet_is_dropped():
    learner = "fehler eins " + " ".join(["wort"] * 99)
    score = _density_score(learner, ["fehler eins", "Ich habe nie in Berlin gewohnt"])
    assert score is not None
    assert score.grammar_errors == ["fehler eins"]
    assert score.dropped_evidence >= 1


def test_missing_grammar_errors_is_empty_and_warns(caplog):
    data = payload()
    del data["grammar_errors"]
    with caplog.at_level(logging.WARNING, logger="kerstin.score"):
        score = parse_score(json.dumps(data), LEARNER)
    assert score is not None
    assert score.grammar_errors == []
    assert "grammar_errors" in caplog.text


def test_grammar_evidence_is_swapped_for_capped_band():
    learner = "fehler eins " + " ".join(["wort"] * 99)
    score = _density_score(learner, ["fehler eins"], grammar_band=2)
    assert score is not None
    assert score.criteria[-1].band == 2
    assert score.criteria[-1].evidence == "fehler eins"
