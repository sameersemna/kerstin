"""Exam content, plan and moderation tests (no network, no GPU)."""

from __future__ import annotations

import copy
import json

import pytest

from kerstin.config import BACKEND_DIR
from kerstin.exam import MODERATION_PREFIX, is_moderation, load_presets, make_plan
from kerstin.prompts import PromptStore
from kerstin.session import Deps, Session, exam_enter_marker
from kerstin.tts import NoTTS


def catalog() -> dict:
    return load_presets(BACKEND_DIR / "prompts")


def key(card: dict | None) -> str:
    assert card
    return str(card.get("title") or card.get("question") or card.get("situation"))


def test_real_exam_json_validates_and_pools_are_large_enough():
    data = catalog()
    assert len(data["presets"]) == 2
    assert len(data["pools"]["talk_topics"]) >= 8
    assert len(data["pools"]["kerstin_topics"]) >= 4
    assert len(data["pools"]["discussion_questions"]) >= 6
    assert len(data["pools"]["planning_tasks"]) >= 6


def test_make_plan_is_deterministic_and_has_no_repeated_cards():
    data = catalog()
    first = make_plan("praesentation_diskussion_planung", data, 1234)
    second = make_plan("praesentation_diskussion_planung", data, 1234)

    assert first == second
    assert [part.kind for part in first.parts] == [
        "prep",
        "learner_talk",
        "kerstin_talk",
        "dialog",
        "dialog",
    ]
    talk_cards = [
        key(part.card)
        for part in first.parts
        if part.kind in ("prep", "learner_talk")
    ]
    assert len(set(talk_cards)) == 1
    for kind in ("kerstin_talk", "dialog"):
        cards = [key(part.card) for part in first.parts if part.kind == kind]
        assert len(cards) == len(set(cards))


def test_make_plan_unknown_preset():
    with pytest.raises(ValueError):
        make_plan("does_not_exist", catalog(), 1)


def test_is_moderation():
    assert is_moderation({"role": "user", "content": MODERATION_PREFIX + "Teil 2"})
    assert not is_moderation({"role": "assistant", "content": MODERATION_PREFIX + "x"})
    assert not is_moderation({"role": "user", "content": "Teil 2"})


def test_broken_preset_kind_and_seconds_raise(tmp_path):
    data = copy.deepcopy(catalog())
    data["presets"]["praesentation_diskussion_planung"]["parts"][0]["kind"] = "nope"
    path = tmp_path / "exam.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_presets(tmp_path)

    data = copy.deepcopy(catalog())
    data["presets"]["praesentation_diskussion_planung"]["parts"][0]["seconds"] = 0
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_presets(tmp_path)


def test_broken_pool_size_raises(tmp_path):
    data = copy.deepcopy(catalog())
    data["pools"]["talk_topics"] = data["pools"]["talk_topics"][:7]
    path = tmp_path / "exam.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_presets(tmp_path)


def test_prompt_content_has_no_official_brand_names():
    text = (
        (BACKEND_DIR / "prompts" / "exam.json").read_text(encoding="utf-8")
        + (BACKEND_DIR / "prompts" / "exam.md").read_text(encoding="utf-8")
    ).lower()
    for brand in ("telc", "goethe", "testdaf", "ösd", "osd"):
        assert brand not in text


def test_make_plan_can_pin_cards_by_title_question_or_situation():
    pins = {
        "talk_topics": "Arbeit im Homeoffice",
        "kerstin_topics": "Mein Weg nach Berlin",
        "discussion_questions": "Sollten Städte autofreie Zonen einrichten?",
        "planning_tasks": "Der Deutschkurs endet nächsten Monat. Plant gemeinsam ein Abschiedsfest.",
    }
    plan = make_plan("praesentation_diskussion_planung", catalog(), 1, cards=pins)

    assert [key(part.card) for part in plan.parts] == [
        "Arbeit im Homeoffice",
        "Arbeit im Homeoffice",
        "Mein Weg nach Berlin",
        "Sollten Städte autofreie Zonen einrichten?",
        "Der Deutschkurs endet nächsten Monat. Plant gemeinsam ein Abschiedsfest.",
    ]


def test_make_plan_unknown_pinned_title_raises():
    with pytest.raises(ValueError):
        make_plan(
            "praesentation_diskussion_planung",
            catalog(),
            1,
            cards={"talk_topics": "Diese Karte gibt es nicht"},
        )


def test_exam_enter_markers_are_part_specific():
    plan = make_plan("praesentation_diskussion_planung", catalog(), 1)

    talk = exam_enter_marker(plan.parts[2], 2)
    assert talk
    assert "du" in talk
    assert "nie ‚ihr/euch‘" in talk

    planning = exam_enter_marker(plan.parts[4], 4)
    assert planning
    assert "Vorschlag" in planning

    discussion = exam_enter_marker(plan.parts[3], 3)
    assert discussion
    assert "klaren eigenen Position" in discussion

    assert exam_enter_marker(plan.parts[0], 0) is None
    assert exam_enter_marker(plan.parts[1], 1) is None


PCM_1S = b"\x00\x40" * 16000


class CountingSTT:
    def __init__(self):
        self.calls = 0
        self.text = "Ich möchte etwas sagen."

    async def transcribe(self, pcm16):
        self.calls += 1
        return self.text


class FakeLLM:
    def __init__(self):
        self.stream_calls = 0

    async def stream_chat(self, messages, max_tokens=None):
        self.stream_calls += 1
        yield "Hallo."


async def test_prep_guard_drops_before_stt_and_collect_after_exam_next():
    plan = make_plan("praesentation_diskussion_planung", catalog(), 1)
    stt = CountingSTT()
    llm = FakeLLM()
    sent = []

    async def send_json(message):
        sent.append(message)

    async def send_bytes(data):
        return None

    session = Session(
        deps=Deps(
            stt=stt,
            llm=llm,
            tts=NoTTS(),
            prompts=PromptStore(BACKEND_DIR / "prompts"),
            llm_warmup=False,
        ),
        send_json=send_json,
        send_bytes=send_bytes,
        scenario_key="freies_gespraech",
        exam=plan,
    )

    await session.start()
    assert sent[-1]["type"] == "exam_part"
    assert sent[-1]["kind"] == "prep"

    await session.handle_audio(PCM_1S)
    await session._turn_task
    assert stt.calls == 0
    assert sent[-1] == {"type": "stt_empty", "turn": 1, "reason": "prep"}
    assert session.turn_id == 1

    await session.exam_next()
    assert sent[-1]["type"] == "exam_part"
    assert sent[-1]["index"] == 1
    assert sent[-1]["kind"] == "learner_talk"

    await session.handle_audio(PCM_1S)
    await session._turn_task
    assert stt.calls == 1
    assert sent[-1] == {"type": "collected", "turn": 2}
    assert session.turn_id == 2
    assert llm.stream_calls == 0


LONG_LEARNER = (
    "Ich wohne seit zwei Jahren in Berlin und arbeite dort als Designerin. "
    "Am Anfang war die Wohnungssuche schwierig, aber inzwischen kenne ich die Stadt gut. "
    "Ich fahre meistens mit dem Fahrrad und kaufe auf dem Markt ein. "
    "Meiner Meinung nach ist das Leben in der Stadt praktisch, weil alles nah ist. "
    "Allerdings sind die Mieten hoch und es ist oft laut. "
    "Trotzdem möchte ich vorerst hier bleiben und später vielleicht an den Stadtrand ziehen. "
    "Für mich ist wichtig, dass ich kurze Wege habe und viele kulturelle Angebote nutzen kann. "
    "Deshalb finde ich die Stadt für junge Menschen besonders geeignet."
)

SCORE_JSON = json.dumps(
    {
        "aufgabe": {
            "band": 2,
            "reason": "Die Aufgabe ist teilweise erfüllt.",
            "evidence": "Ich wohne seit zwei Jahren",
        },
        "kohaerenz": {
            "band": 3,
            "reason": "Die Aussagen sind verbunden.",
            "evidence": "weil alles nah ist",
        },
        "wortschatz": {
            "band": 3,
            "reason": "Der Wortschatz passt zum Thema.",
            "evidence": "die Mieten hoch",
        },
        "grammatik": {
            "band": 4,
            "reason": "Die Strukturen sind sicher.",
            "evidence": "Trotzdem möchte ich vorerst hier bleiben",
        },
        "grammar_errors": [],
    }
)


class ScoringLLM:
    def __init__(self, score_json=SCORE_JSON):
        self.score_json = score_json
        self.chat_calls = 0
        self.last_chat_temperature = None
        self.last_chat_model = None
        self.last_chat_seed = None
        self.last_chat_fmt = None

    async def stream_chat(self, messages, max_tokens=None):
        yield "Hallo."

    async def chat(
        self,
        messages,
        max_tokens=None,
        temperature=None,
        model=None,
        keep_alive=None,
        fmt=None,
        seed=None,
    ):
        self.chat_calls += 1
        self.last_chat_temperature = temperature
        self.last_chat_model = model
        self.last_chat_seed = seed
        self.last_chat_fmt = fmt
        if self.chat_calls == 1:
            return "### Feedback"
        return self.score_json


def scoring_session(llm, exam, learner=LONG_LEARNER):
    sent = []

    async def send_json(message):
        sent.append(message)

    async def send_bytes(data):
        return None

    session = Session(
        deps=Deps(
            stt=CountingSTT(),
            llm=llm,
            tts=NoTTS(),
            prompts=PromptStore(BACKEND_DIR / "prompts"),
            llm_warmup=False,
            score_seed=7,
        ),
        send_json=send_json,
        send_bytes=send_bytes,
        scenario_key="freies_gespraech",
        exam=exam,
        history=[
            {"role": "assistant", "content": "Hallo."},
            {"role": "user", "content": learner},
        ],
    )
    return session, sent


async def test_exam_feedback_is_followed_by_exam_score():
    llm = ScoringLLM()
    session, sent = scoring_session(
        llm, make_plan("vortrag_diskussion", catalog(), 1)
    )

    await session.feedback()

    types = [message["type"] for message in sent]
    assert types.index("feedback") < types.index("exam_score")
    score = next(message for message in sent if message["type"] == "exam_score")
    assert [criterion["key"] for criterion in score["criteria"]] == [
        "aufgabe",
        "kohaerenz",
        "wortschatz",
        "grammatik",
    ]
    assert [criterion["band"] for criterion in score["criteria"]] == [2, 3, 3, 4]
    assert score["overall_band"] == 3
    assert score["overall_label"] == "B2 sicher"
    assert score["error_density"] == 0.0
    assert score["grammar_errors"] == []
    assert score["note"]
    assert llm.chat_calls == 2
    assert llm.last_chat_temperature == 0.0
    assert llm.last_chat_model == "gemma4:26b"
    assert llm.last_chat_seed == 7
    assert llm.last_chat_fmt == "json"


async def test_exam_feedback_too_short_skips_score_llm():
    llm = ScoringLLM()
    session, sent = scoring_session(
        llm,
        make_plan("vortrag_diskussion", catalog(), 1),
        learner="Ich wohne in Berlin.",
    )

    await session.feedback()

    score = next(message for message in sent if message["type"] == "exam_score")
    assert score == {
        "type": "exam_score",
        "error": "zu wenig Material für eine Einschätzung",
    }
    assert llm.chat_calls == 1


async def test_free_conversation_feedback_has_no_exam_score():
    llm = ScoringLLM()
    session, sent = scoring_session(llm, None)

    await session.feedback()

    assert [message["type"] for message in sent] == ["status", "feedback"]
    assert not any(message["type"] == "exam_score" for message in sent)
    assert llm.chat_calls == 1
