#!/usr/bin/env python3
"""Headless eval for the B2 exam engine, both presets, real Ollama and Session."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from dataclasses import dataclass

from kerstin.config import Settings
from kerstin.exam import load_presets, make_plan
from kerstin.llm import OllamaLLM
from kerstin.prompts import PromptStore
from kerstin.reply_checks import check_reply, count_sentences
from kerstin.session import Deps, Session
from kerstin.tts import NoTTS
from smoke_test import COOL_AT_C, COOL_TO_C, ThermalAbort, cool_down

PCM_1S = b"\x00\x40" * 16000  # 1 s at -6 dBFS; scripted STT ignores the samples
TURN_TIMEOUT_S = 240.0
TALK_LINES = (
    "Ich möchte heute über ein Thema aus meinem Alltag sprechen.",
    "In meinem Heimatland ist die Situation anders als hier in Deutschland.",
    "Ich habe damit selbst schon gute und schlechte Erfahrungen gemacht.",
    "Meiner Meinung nach ist das Thema wichtig, aber es gibt auch Grenzen.",
)
ANSWER_LINE = "Meine wichtigste Erfahrung war der erste Monat in meinem neuen Job."
QUESTIONS = (
    "Wie war das für dich am Anfang?",
    "Was hast du daraus gelernt?",
)
DIALOG_LINES = (
    "Ich finde, man sollte zuerst die öffentlichen Verkehrsmittel verbessern.",
    "Aber was ist mit den Menschen, die auf das Auto angewiesen sind?",
    "Wir könnten zuerst einen passenden Ort suchen.",
    "Ich übernehme gern die Aufgabe mit den Getränken.",
)


class EvalError(Exception):
    """The eval could not complete a turn."""


class ScriptedSTT:
    def __init__(self) -> None:
        self.text = ""

    async def transcribe(self, pcm16: bytes) -> str:
        return self.text


class CountingLLM(OllamaLLM):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.stream_calls = 0
        self.chat_calls = 0

    async def stream_chat(self, messages, max_tokens=None):
        self.stream_calls += 1
        async for piece in super().stream_chat(messages, max_tokens=max_tokens):
            yield piece

    async def chat(self, messages, max_tokens=1200, **kwargs):
        self.chat_calls += 1
        return await super().chat(messages, max_tokens=max_tokens, **kwargs)


@dataclass
class Reply:
    part: int | None
    turn: int
    text: str
    metrics: dict | None


def parse_replies(messages: list[dict]) -> list[Reply]:
    current: int | None = None
    by_turn: dict[int, dict] = {}
    order: list[int] = []
    for message in messages:
        kind = message.get("type")
        if kind == "exam_part" and "index" in message:
            current = int(message["index"])
        elif kind == "reply_text":
            turn = int(message["turn"])
            if turn not in by_turn:
                by_turn[turn] = {"part": current, "text": [], "metrics": None}
                order.append(turn)
            by_turn[turn]["text"].append(message["text"])
        elif kind == "metrics":
            turn = int(message["turn"])
            if turn in by_turn:
                by_turn[turn]["metrics"] = message
    return [
        Reply(
            part=by_turn[turn]["part"],
            turn=turn,
            text=" ".join(by_turn[turn]["text"]).strip(),
            metrics=by_turn[turn]["metrics"],
        )
        for turn in order
    ]


def _talk_markdown(text: str) -> bool:
    if any(marker in text for marker in ("*", "#", "`")):
        return True
    return any(line.lstrip().startswith("-") for line in text.splitlines())


def _first_reply(replies: list[Reply], part_index: int) -> Reply | None:
    return next((reply for reply in replies if reply.part == part_index), None)


async def _wait_turn(session: Session, where: str) -> None:
    task = session._turn_task
    if task is None:
        raise EvalError(f"{where}: no turn task")
    try:
        await asyncio.wait_for(task, timeout=TURN_TIMEOUT_S)
    except TimeoutError as exc:
        raise EvalError(f"{where}: timeout") from exc


async def _handle_line(session: Session, stt: ScriptedSTT, line: str, where: str) -> None:
    stt.text = line
    await session.handle_audio(PCM_1S)
    await _wait_turn(session, where)


async def run_preset(
    preset_key: str,
    data: dict,
    settings: Settings,
    args: argparse.Namespace,
) -> tuple[list[Reply], list[str], int]:
    plan = make_plan(preset_key, data, args.seed)
    llm = CountingLLM(settings)
    stt = ScriptedSTT()
    messages: list[dict] = []

    async def send_json(obj: dict) -> None:
        messages.append(obj)

    async def send_bytes(data: bytes) -> None:
        return None

    session = Session(
        deps=Deps(
            stt=stt,
            llm=llm,
            tts=NoTTS(),
            prompts=PromptStore(settings.prompts_dir),
            history_max_turns=settings.history_max_turns,
            llm_warmup=False,
            first_clause_min_words=settings.tts_first_clause_min_words,
        ),
        send_json=send_json,
        send_bytes=send_bytes,
        scenario_key=settings.default_scenario,
        exam=plan,
    )

    collect_calls = 0
    try:
        await cool_down("before exam start", args.cool_at, args.cool_to)
        await session.start()
        for index, part in enumerate(plan.parts):
            where = f"{preset_key} part {index} {part.kind}"
            if part.kind == "prep":
                await cool_down(f"before {where} next", args.cool_at, args.cool_to)
                await session.exam_next()
                continue
            if part.kind == "learner_talk":
                before = llm.stream_calls
                for line_index, line in enumerate(TALK_LINES, 1):
                    await cool_down(f"before {where} collect {line_index}", args.cool_at, args.cool_to)
                    await _handle_line(session, stt, line, f"{where} collect {line_index}")
                collect_calls = llm.stream_calls - before
                await cool_down(f"before {where} follow-up", args.cool_at, args.cool_to)
                await session.exam_next()
                await cool_down(f"before {where} answer", args.cool_at, args.cool_to)
                await _handle_line(session, stt, ANSWER_LINE, f"{where} answer")
                await cool_down(f"before {where} next", args.cool_at, args.cool_to)
                await session.exam_next()
                continue
            if part.kind == "kerstin_talk":
                for question_index, question in enumerate(QUESTIONS, 1):
                    await cool_down(
                        f"before {where} question {question_index}",
                        args.cool_at,
                        args.cool_to,
                    )
                    await _handle_line(session, stt, question, f"{where} question {question_index}")
                await cool_down(f"before {where} next", args.cool_at, args.cool_to)
                await session.exam_next()
                continue
            if part.kind == "dialog":
                for line_index, line in enumerate(DIALOG_LINES, 1):
                    await cool_down(f"before {where} turn {line_index}", args.cool_at, args.cool_to)
                    await _handle_line(session, stt, line, f"{where} turn {line_index}")
                await cool_down(f"before {where} next", args.cool_at, args.cool_to)
                await session.exam_next()

        errors = [message for message in messages if message.get("type") in ("error", "thermal")]
        if errors:
            raise EvalError(f"{preset_key}: {errors[0]}")
    finally:
        await session.close()
        await llm.client.aclose()

    return parse_replies(messages), collect_calls


def print_preset(preset_key: str, plan, replies: list[Reply], collect_calls: int) -> list[str]:
    failures: list[str] = []
    print(f"\n## Preset `{preset_key}` — {plan.title}")
    print(
        "Parts: "
        + ", ".join(f"{index}:{part.kind}" for index, part in enumerate(plan.parts))
    )
    print(f"Collect-mode LLM calls: {collect_calls}")
    if collect_calls != 0:
        failures.append("collect LLM calls > 0")

    learner_parts = [index for index, part in enumerate(plan.parts) if part.kind == "learner_talk"]
    talk_parts = [index for index, part in enumerate(plan.parts) if part.kind == "kerstin_talk"]
    discussion_parts = [
        index for index, part in enumerate(plan.parts) if part.kind == "dialog" and "plan" not in part.title.lower()
    ]
    planning_parts = [
        index for index, part in enumerate(plan.parts) if part.kind == "dialog" and "plan" in part.title.lower()
    ]

    follow_up = _first_reply(replies, learner_parts[0]) if learner_parts else None
    if follow_up is None:
        failures.append("missing follow-up")
        print("Follow-up: MISSING")
    else:
        follow_up_ok = follow_up.text.rstrip().endswith("?") and count_sentences(follow_up.text) <= 2
        print(f"Follow-up: {follow_up.text}  [one-question={follow_up_ok}]")
        if not follow_up_ok:
            failures.append("follow-up is not one question")

    talk = _first_reply(replies, talk_parts[0]) if talk_parts else None
    if talk is None:
        failures.append("missing Kerstin talk")
        print("Kerstin talk: MISSING")
    else:
        talk_part = plan.parts[talk_parts[0]]
        expected = talk_part.talk_words or 0
        low, high = int(expected * 0.65), int(expected * 1.35)
        words = len(talk.text.split())
        markdown = _talk_markdown(talk.text)
        print(
            f"Kerstin talk: {words} words (target {expected}, range {low}–{high}); "
            f"markdown={markdown}"
        )
        if not (low <= words <= high):
            failures.append("talk length outside range")
        if markdown:
            failures.append("talk contains markdown/bullets")
        metrics = talk.metrics or {}
        print(
            "Kerstin talk timing: "
            f"first_sentence_ms={metrics.get('first_sentence_ms')} "
            f"tts_first_ms={metrics.get('tts_first_ms')} "
            f"first_audio_ms={metrics.get('first_audio_ms')} "
            f"llm_first_token_ms={metrics.get('llm_first_token_ms')}"
        )
        if metrics.get("first_audio_ms") is None:
            failures.append("talk has no first-audio metric")

    def first_for(parts: list[int]) -> Reply | None:
        return _first_reply(replies, parts[0]) if parts else None

    discussion = first_for(discussion_parts)
    if discussion is not None:
        ok = bool(
            re.search(
                r"\b(ich finde|meiner meinung nach|ich bin der meinung|ich glaube)\b",
                discussion.text,
                re.IGNORECASE,
            )
        )
        print(f"Discussion opener: {discussion.text}  [position={ok}]")
        if not ok:
            failures.append("discussion opener lacks position")
    else:
        print("Discussion opener: n/a")

    planning = first_for(planning_parts)
    if planning is not None:
        ok = bool(
            re.search(
                r"\b(wir k(ö|oe)nnten|lass uns|wie w(ä|ae)re es|ich schlage vor)\b",
                planning.text,
                re.IGNORECASE,
            )
        )
        print(f"Planning opener: {planning.text}  [proposal={ok}]")
        if not ok:
            failures.append("planning opener lacks proposal")
    else:
        print("Planning opener: n/a")

    talk_turn = talk.turn if talk is not None else None
    normal = [
        reply
        for reply in replies
        if reply.part is not None and reply.turn != talk_turn and reply.text
    ]
    dialog_codes = {reply.turn: check_reply(reply.text) for reply in normal}
    bad = {turn: codes for turn, codes in dialog_codes.items() if codes}
    print(f"Dialog check_reply: {len(normal)} replies, issues={bad or 'none'}")
    if bad:
        failures.append("dialog replies fail check_reply")

    leaks = [reply for reply in replies if "moderation" in reply.text.lower()]
    print(f"Moderation leaks: {len(leaks)}")
    if leaks:
        failures.append("moderation leak")

    print(f"Overall: {'FAIL' if failures else 'PASS'}")
    return failures


def print_replies(plan, replies: list[Reply]) -> None:
    print("\nReplies by part")
    for reply in replies:
        if reply.part is None:
            print(f"\n[Greeting] T{reply.turn}: {reply.text}")
    for index, part in enumerate(plan.parts):
        grouped = [reply for reply in replies if reply.part == index]
        print(f"\n[{index}] {part.kind} — {part.title}")
        if not grouped:
            print("  (no reply)")
            continue
        for reply in grouped:
            codes = check_reply(reply.text)
            print(f"  T{reply.turn}: {reply.text}  [codes: {', '.join(codes) or '-'}]")


async def run(args: argparse.Namespace) -> int:
    os.environ["KERSTIN_LLM_SEED"] = str(args.seed)
    overrides = {"ollama_model": args.model} if args.model else {}
    settings = Settings(**overrides)
    data = load_presets(settings.prompts_dir)
    print(
        f"Model: {settings.ollama_model} | seed: {args.seed} | "
        f"cool_down: {args.cool_at}→{args.cool_to} °C"
    )
    failures: list[str] = []
    for preset_key in data["presets"]:
        plan = make_plan(preset_key, data, args.seed)
        replies, collect_calls = await run_preset(preset_key, data, settings, args)
        failures += print_preset(preset_key, plan, replies, collect_calls)
        print_replies(plan, replies)
    if failures:
        print(f"\nFAILURES: {failures}")
        return 1
    print("\nAll automatic checks passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None, help="override ollama_model")
    parser.add_argument("--seed", type=int, default=1234, help="plan and LLM seed")
    parser.add_argument("--cool-at", type=float, default=COOL_AT_C)
    parser.add_argument("--cool-to", type=float, default=COOL_TO_C)
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except ThermalAbort as exc:
        print(f"ABORT: {exc}", file=sys.stderr)
        return 3
    except EvalError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
