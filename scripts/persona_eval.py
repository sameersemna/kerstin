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
import re
import shutil
import statistics
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
from smoke_test import COOL_AT_C, COOL_TO_C, ThermalAbort, cool_down

PCM_1S = b"\x00\x40" * 16000  # 1 s at -6 dBFS; scripted STT ignores the samples
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
    llm_first_token_ms: int | None = None


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
        shutil.copy(settings.prompts_dir / "focus.json", tmp_dir / "focus.json")
        shutil.copy(candidate, tmp_dir / "persona.md")
        yield PromptStore(tmp_dir)


async def run_scenario(
    scenario_key: str,
    lines: list[LearnerLine],
    settings: Settings,
    llm: OllamaLLM,
    prompts: PromptStore,
    args: argparse.Namespace,
    scenario_index: int,
    focus_keys: list[str],
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
        focus=focus_keys,
    )

    results: list[TurnResult] = []
    print(f"\n=== {scenario_key} ===")
    try:
        await cool_down(f"before {scenario_key} start", args.cool_at, args.cool_to)
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
            print(f"Kerstin [S{scenario_index}-T0]: {opener}")

        for index, line in enumerate(lines, 1):
            reply_id = f"S{scenario_index}-T{index}"
            await cool_down(f"before {reply_id}", args.cool_at, args.cool_to)
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
            metrics = next(
                (
                    message
                    for message in turn_messages
                    if message.get("type") == "metrics"
                    and message.get("turn") == turn_id
                ),
                None,
            )
            allowed = " [Korrektur erlaubt]" if line.correction_allowed else ""
            inline = ", ".join(codes) if codes else "-"
            print(f"Lernende [{reply_id}]{allowed}: {line.text}")
            print(f"Kerstin [{reply_id}]: {reply}  [codes: {inline}]")
            results.append(
                TurnResult(
                    scenario_key,
                    line,
                    reply,
                    codes,
                    metrics.get("llm_first_token_ms") if metrics else None,
                )
            )
            if args.pause > 0:
                await asyncio.sleep(args.pause)
    finally:
        await session.close()

    return results


def invite_rate(results: list[TurnResult], cues: list[str]) -> tuple[int, int]:
    hits = sum(
        1
        for result in results
        if any(re.search(cue, result.reply.lower()) for cue in cues)
    )
    return hits, len(results)


def warm_first_tokens(results: list[TurnResult]) -> list[int]:
    seen: set[str] = set()
    values: list[int] = []
    for result in results:
        if result.scenario in seen and result.llm_first_token_ms is not None:
            values.append(result.llm_first_token_ms)
        seen.add(result.scenario)
    return values


def print_summary(
    results: list[TurnResult],
    gpu_start: int | None,
    gpu_end: int | None,
    model: str,
    focus_keys: list[str],
    focus_cues: list[str],
) -> None:
    code_counts = Counter(code for result in results for code in result.codes)
    total = len(results)
    mean_sentences = (
        sum(count_sentences(result.reply) for result in results) / total if total else 0.0
    )
    mean_words = sum(len(result.reply.split()) for result in results) / total if total else 0.0

    print("\nSummary")
    print(f"model: {model}")
    print(f"focus: {', '.join(focus_keys) if focus_keys else 'none'}")
    print(f"{'code':<20}{'count':>6}")
    print("-" * 26)
    for code in (
        "too_long",
        "no_question",
        "markdown_or_emoji",
        "digits",
        "english",
        "correction",
        "meta_talk",
    ):
        print(f"{code:<20}{code_counts.get(code, 0):>6}")
    print(f"\ntotal replies: {total}")
    print(f"mean sentences/reply: {mean_sentences:.2f}")
    print(f"mean words/reply: {mean_words:.2f}")
    if focus_cues:
        hits, count = invite_rate(results, focus_cues)
        print(f"invite rate (focus cues): {hits}/{count} = {100 * hits / count:.0f}%")
    else:
        print("invite rate (focus cues): n/a (no focus)")
    warm = warm_first_tokens(results)
    if warm:
        print(f"llm_first_token_ms p50 (warm): {statistics.median(warm):.0f}")
    else:
        print("llm_first_token_ms p50 (warm): n/a")
    print(f"GPU: start {gpu_start} °C, end {gpu_end} °C")


def print_meta_talk(results: list[TurnResult]) -> None:
    print("\nMeta-talk hits")
    hits = [result for result in results if "meta_talk" in result.codes]
    if not hits:
        print("none")
        return
    for index, result in enumerate(hits, 1):
        print(f"{index}. [{result.scenario}] {result.reply}")


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
    overrides = {"ollama_model": args.model} if args.model else {}
    settings = Settings(**overrides)
    llm = OllamaLLM(settings)
    focus_keys = [key.strip() for key in args.focus.split(",") if key.strip()]
    print(
        f"\nModel: {settings.ollama_model} | seed: {args.seed} | "
        f"focus: {', '.join(focus_keys) if focus_keys else 'none'}"
    )
    try:
        with prompt_store(settings, args.persona) as prompts:
            scenario_keys = list(SCRIPT) if args.scenario is None else [args.scenario]
            scenario_order = list(SCRIPT)
            instructions = prompts.focus_instructions()
            unknown = [key for key in focus_keys if key not in instructions]
            if unknown:
                raise EvalError(f"unknown focus: {', '.join(unknown)}")
            focus_cues = [
                cue for key in focus_keys for cue in instructions[key]["cues"]
            ]
            gpu_start = await cool_down("at start", args.cool_at, args.cool_to)
            results: list[TurnResult] = []
            for scenario_key in scenario_keys:
                prompts.scenario(scenario_key)
                scenario_index = scenario_order.index(scenario_key) + 1
                results += await run_scenario(
                    scenario_key,
                    SCRIPT[scenario_key],
                    settings,
                    llm,
                    prompts,
                    args,
                    scenario_index,
                    focus_keys,
                )
            gpu_end = await cool_down("at end", args.cool_at, args.cool_to)
        print_summary(
            results,
            gpu_start,
            gpu_end,
            settings.ollama_model,
            focus_keys,
            focus_cues,
        )
        print_meta_talk(results)
        print_corrections(results)
    finally:
        await llm.client.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--scenario", choices=list(SCRIPT), default=None)
    parser.add_argument("--model", default=None, help="override ollama_model for this run")
    parser.add_argument(
        "--focus",
        default="",
        help="comma-separated focus keys (e.g. verbposition or perfekt_hilfsverb,praeposition)",
    )
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between turns")
    parser.add_argument("--cool-at", type=int, default=COOL_AT_C)
    parser.add_argument("--cool-to", type=int, default=COOL_TO_C)
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
