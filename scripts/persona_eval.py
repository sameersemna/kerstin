#!/usr/bin/env python3
"""Scripted text-only persona eval over the real Session and Ollama.

Runs 6 learner lines in each of the 5 scenarios, prints the full transcript,
violation codes, a summary and the non-allowed correction flags. Output goes
to stdout only.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
import tempfile
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from kerstin.config import PROJECT_DIR, Settings
from kerstin.llm import OllamaLLM
from kerstin.prompts import PromptStore
from kerstin.reply_checks import check_reply, count_sentences
from kerstin.session import Deps, Session
from kerstin.tts import NoTTS
from smoke_test import ThermalAbort, thermal_guard

PCM_1S = b"\x00\x00" * 16000
TURN_TIMEOUT_S = 180.0
ENGLISH_LINE = "Sorry, how do you say 'deadline' in German?"


class EvalError(Exception):
    """The eval could not complete a turn."""


@dataclass(frozen=True)
class LearnerLine:
    text: str
    correction_allowed: bool = False


@dataclass(frozen=True)
class TurnResult:
    scenario: str
    line: LearnerLine
    reply: str
    codes: list[str]


SCRIPT: dict[str, list[LearnerLine]] = {
    "freies_gespraech": [
        LearnerLine("Ich wohne seit drei Jahren in Berlin und fühle mich hier schon zu Hause."),
        LearnerLine(
            "Ich habe gestern mit ein Freund ins Kino gegangen, aber der Film war langweilig."
        ),
        LearnerLine(
            "Weil ich diese Woche viel gearbeitet habe, ich bin am Wochenende ziemlich müde."
        ),
        LearnerLine(ENGLISH_LINE),
        LearnerLine("Ich wohne seit drei Jahren in Berlin und fühle mich hier schon zu Hause."),
        LearnerLine(
            "Kannst du mich bitte korrigieren? Ich habe gesagt: Ich freue mich auf der Sommer.",
            correction_allowed=True,
        ),
    ],
    "wg_alltag": [
        LearnerLine(
            "Ich finde, wir sollten den Putzplan einmal zusammen durchgehen und fair aufteilen."
        ),
        LearnerLine(
            "Ich habe gestern die Küche geputzt, aber danach hat mein Mitbewohner sein "
            "Geschirr wieder auf der Tisch gestellt."
        ),
        LearnerLine("Weil die Küche oft unordentlich ist, ich möchte nicht mehr allein putzen."),
        LearnerLine(ENGLISH_LINE),
        LearnerLine(
            "Ich finde, wir sollten den Putzplan einmal zusammen durchgehen und fair aufteilen."
        ),
        LearnerLine(
            "Kannst du mich bitte korrigieren? Ich habe gesagt: Ich habe die Küche geputzt, "
            "aber danach hat mein Mitbewohner sein Geschirr wieder auf der Tisch gestellt.",
            correction_allowed=True,
        ),
    ],
    "arbeit_kollegen": [
        LearnerLine(
            "Ich finde die neuen Homeoffice-Regeln eigentlich ganz sinnvoll, aber zwei Tage "
            "sind vielleicht etwas wenig."
        ),
        LearnerLine(
            "Ich habe gestern mit mein Chef über das neue Projekt gesprochen, aber er war "
            "nicht zufrieden."
        ),
        LearnerLine(
            "Weil das Projekt nächste Woche startet, ich muss am Wochenende noch viel vorbereiten."
        ),
        LearnerLine(ENGLISH_LINE),
        LearnerLine(
            "Ich finde die neuen Homeoffice-Regeln eigentlich ganz sinnvoll, aber zwei Tage "
            "sind vielleicht etwas wenig."
        ),
        LearnerLine(
            "Kannst du mich bitte korrigieren? Ich habe gesagt: Ich habe gestern mit mein Chef "
            "über das Projekt gesprochen.",
            correction_allowed=True,
        ),
    ],
    "diskussion": [
        LearnerLine(
            "Ich finde, man sollte die Innenstadt nicht komplett autofrei machen, sondern "
            "zuerst den öffentlichen Verkehr verbessern."
        ),
        LearnerLine(
            "Meiner Meinung nach, die Autos sind nicht das größte Problem, sondern der viele "
            "Lieferverkehr."
        ),
        LearnerLine(
            "Ich habe letztes Jahr in Kopenhagen gesehen, wie gut das mit die Fahrräder "
            "funktioniert hat."
        ),
        LearnerLine(ENGLISH_LINE),
        LearnerLine(
            "Ich finde, man sollte die Innenstadt nicht komplett autofrei machen, sondern "
            "zuerst den öffentlichen Verkehr verbessern."
        ),
        LearnerLine(
            "Kannst du mich bitte korrigieren? Ich habe gesagt: Meiner Meinung nach, die Autos "
            "sind nicht das größte Problem.",
            correction_allowed=True,
        ),
    ],
    "pruefung_planung": [
        LearnerLine(
            "Ich schlage vor, dass wir die Feier im Kursraum machen, weil das am günstigsten ist."
        ),
        LearnerLine(
            "Ich denke, wir sollten das Geschenk zusammen kaufen, weil es ist persönlicher."
        ),
        LearnerLine(
            "Für die Einladungen könnte ich am Wochenende schreiben, wenn ihr mir die Namen geben."
        ),
        LearnerLine(ENGLISH_LINE),
        LearnerLine(
            "Ich schlage vor, dass wir die Feier im Kursraum machen, weil das am günstigsten ist."
        ),
        LearnerLine(
            "Kannst du mich bitte korrigieren? Ich habe gesagt: Ich denke, wir sollten das "
            "Geschenk zusammen kaufen, weil es ist persönlicher.",
            correction_allowed=True,
        ),
    ],
}


class ScriptedSTT:
    def __init__(self) -> None:
        self.text = ""

    async def transcribe(self, pcm16: bytes) -> str:
        return self.text


@contextmanager
def prompt_store(settings: Settings, persona_path: Path):
    default_persona = (settings.prompts_dir / "persona.md").resolve()
    candidate = persona_path.resolve()
    if candidate == default_persona:
        yield PromptStore(settings.prompts_dir)
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        shutil.copy(settings.prompts_dir / "scenarios.json", tmp_dir / "scenarios.json")
        shutil.copy(candidate, tmp_dir / "persona.md")
        yield PromptStore(tmp_dir)


async def run_scenario(
    scenario_key: str,
    lines: list[LearnerLine],
    settings: Settings,
    llm: OllamaLLM,
    prompts: PromptStore,
) -> list[TurnResult]:
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
            prompts=prompts,
            history_max_turns=settings.history_max_turns,
            llm_warmup=settings.llm_warmup,
            first_clause_min_words=settings.tts_first_clause_min_words,
        ),
        send_json=send_json,
        send_bytes=send_bytes,
        scenario_key=scenario_key,
    )

    results: list[TurnResult] = []
    print(f"\n=== {scenario_key} ===")
    try:
        await session.start()
        opener = next(
            (
                message["text"]
                for message in messages
                if message.get("type") == "reply_text" and message.get("turn") == 0
            ),
            "",
        )
        if opener:
            print(f"Kerstin (Opener): {opener}")

        for index, line in enumerate(lines, 1):
            thermal_guard(f"before {scenario_key} turn {index}")
            stt.text = line.text
            start = len(messages)
            await session.handle_audio(PCM_1S)
            turn_id = session.turn_id
            task = session._turn_task
            if task is None:
                raise EvalError(f"{scenario_key} turn {index}: no turn task")
            try:
                await asyncio.wait_for(task, timeout=TURN_TIMEOUT_S)
            except TimeoutError as exc:
                raise EvalError(f"{scenario_key} turn {index}: timeout") from exc

            turn_messages = messages[start:]
            errors = [m for m in turn_messages if m.get("type") == "error"]
            if errors:
                raise EvalError(
                    f"{scenario_key} turn {index}: {errors[0].get('message', 'unknown error')}"
                )
            reply_parts = [
                message["text"]
                for message in turn_messages
                if message.get("type") == "reply_text" and message.get("turn") == turn_id
            ]
            reply = " ".join(reply_parts).strip()
            if not reply:
                raise EvalError(f"{scenario_key} turn {index}: empty reply")

            codes = check_reply(reply)
            allowed = " [Korrektur erlaubt]" if line.correction_allowed else ""
            inline = ", ".join(codes) if codes else "-"
            print(f"Lernende{allowed}: {line.text}")
            print(f"Kerstin: {reply}  [codes: {inline}]")
            results.append(TurnResult(scenario_key, line, reply, codes))
    finally:
        await session.close()

    return results


def print_summary(results: list[TurnResult], gpu_start: int | None, gpu_end: int | None) -> None:
    code_counts = Counter(code for result in results for code in result.codes)
    total = len(results)
    mean_sentences = (
        sum(count_sentences(result.reply) for result in results) / total if total else 0.0
    )
    mean_words = sum(len(result.reply.split()) for result in results) / total if total else 0.0

    print("\n(b) Summary")
    print(f"{'code':<20}{'count':>6}")
    print("-" * 26)
    for code in (
        "too_long",
        "no_question",
        "markdown_or_emoji",
        "digits",
        "english",
        "correction",
    ):
        print(f"{code:<20}{code_counts.get(code, 0):>6}")
    print(f"\ntotal replies: {total}")
    print(f"mean sentences/reply: {mean_sentences:.2f}")
    print(f"mean words/reply: {mean_words:.2f}")
    print(f"GPU: start {gpu_start} °C, end {gpu_end} °C")


def print_corrections(results: list[TurnResult]) -> None:
    print("\n(c) correction flagged where not allowed")
    flagged = [
        result
        for result in results
        if "correction" in result.codes and not result.line.correction_allowed
    ]
    if not flagged:
        print("none")
        return
    for index, result in enumerate(flagged, 1):
        print(f"{index}. [{result.scenario}] {result.line.text}")
        print(f"   Kerstin: {result.reply}")


async def run(args: argparse.Namespace) -> None:
    os.environ["KERSTIN_LLM_SEED"] = str(args.seed)
    settings = Settings()
    llm = OllamaLLM(settings)
    try:
        with prompt_store(settings, args.persona) as prompts:
            scenario_keys = list(SCRIPT) if args.scenario is None else [args.scenario]
            gpu_start = thermal_guard("at start")
            results: list[TurnResult] = []
            for scenario_key in scenario_keys:
                prompts.scenario(scenario_key)
                results += await run_scenario(scenario_key, SCRIPT[scenario_key], settings, llm, prompts)
            gpu_end = thermal_guard("at end")
        print_summary(results, gpu_start, gpu_end)
        print_corrections(results)
    finally:
        await llm.client.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--scenario", choices=list(SCRIPT), default=None)
    parser.add_argument(
        "--persona",
        type=Path,
        default=Path("backend/prompts/persona.md"),
        help="candidate persona file (default: backend/prompts/persona.md)",
    )
    args = parser.parse_args()
    if not args.persona.is_absolute():
        args.persona = PROJECT_DIR / args.persona
    if not args.persona.is_file():
        print(f"persona not found: {args.persona}", file=sys.stderr)
        return 2

    try:
        asyncio.run(run(args))
    except ThermalAbort as exc:
        print(f"ABORT: {exc}")
        return 3
    except EvalError as exc:
        print(f"FAIL: {exc}")
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
