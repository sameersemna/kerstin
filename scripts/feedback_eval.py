#!/usr/bin/env python3
"""Run the fixed-case feedback quality eval and print a Markdown report."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from kerstin.config import PROJECT_DIR, Settings
from kerstin.feedback_checks import FeedbackCheck, check_feedback, check_planted
from kerstin.llm import OllamaLLM
from kerstin.prompts import PromptStore
from kerstin.session import format_feedback_transcript
from kerstin.text import strip_think
from smoke_test import COOL_AT_C, COOL_TO_C, ThermalAbort, cool_down

CASES_PATH = PROJECT_DIR / "scripts" / "feedback_cases.json"


@dataclass(frozen=True)
class EvalResult:
    case_index: int
    scenario: str
    lang: str
    run: int
    seed: int
    markdown: str
    elapsed_ms: int
    check: FeedbackCheck
    planted_outcomes: list[str]


async def thermal(label: str, cool_at: int, cool_to: int) -> int:
    with contextlib.redirect_stdout(sys.stderr):
        return await cool_down(label, cool_at, cool_to)


def load_cases(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def fmt(value: str) -> str:
    return value if value else "(missing)"


def summary_table(results: list[EvalResult], model: str, seed: int) -> str:
    lines = [
        "# Feedback eval",
        "",
        f"Model: `{model}` · seed base: {seed} · runs: {len({r.run for r in results})}",
        "",
        "| language | feedbacks | recall | false_corrections | wrong_corrections | noop_corrections | ungrounded | quotes_kerstin | structure_failures | lang_mismatch | format_noise | mean_feedback_ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for lang in ("en", "de"):
        rows = [result for result in results if result.lang == lang]
        if not rows:
            continue
        planted_total = sum(len(result.planted_outcomes) for result in rows)
        found_total = sum(
            outcome == "found" for result in rows for outcome in result.planted_outcomes
        )
        recall = 100.0 * found_total / planted_total if planted_total else 0.0
        mean_ms = sum(result.elapsed_ms for result in rows) / len(rows)
        lines.append(
            "| "
            + " | ".join(
                [
                    lang,
                    str(len(rows)),
                    f"{recall:.0f}%",
                    str(sum(result.check.false_corrections for result in rows)),
                    str(
                        sum(
                            outcome == "wrong_correction"
                            for result in rows
                            for outcome in result.planted_outcomes
                        )
                    ),
                    str(sum(result.check.noop_corrections for result in rows)),
                    str(sum(result.check.ungrounded for result in rows)),
                    str(sum(result.check.quotes_kerstin for result in rows)),
                    str(sum(not result.check.structure_ok for result in rows)),
                    str(sum(result.check.lang_mismatch for result in rows)),
                    str(sum(result.check.format_noise for result in rows)),
                    f"{mean_ms:.0f}",
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def detail_sections(results: list[EvalResult], cases: list[dict]) -> str:
    lines = []
    current_case = None
    for result in results:
        if result.case_index != current_case:
            current_case = result.case_index
            case = cases[current_case]
            lines += [
                "",
                f"## Case `{case['scenario']}`",
                "",
                "Planted: "
                + "; ".join(
                    f"`{item['category']}` `{item['wrong']}` → `{item['right']}`"
                    for item in case["planted"]
                ),
                "",
            ]

        check = result.check
        lines += [
            f"### {result.lang.upper()} · run {result.run} · seed {result.seed} · {result.elapsed_ms} ms",
            "",
            (
                f"structure={'OK' if check.structure_ok else 'FAIL'} · "
                f"false_corrections={check.false_corrections} · "
                f"wrong_corrections={sum(outcome == 'wrong_correction' for outcome in result.planted_outcomes)} · "
                f"noop_corrections={check.noop_corrections} · "
                f"ungrounded={check.ungrounded} · quotes_kerstin={check.quotes_kerstin} · "
                f"lang_mismatch={check.lang_mismatch} · format_noise={check.format_noise}"
            ),
            "",
        ]

        if not check.errors:
            lines.append("_No ❌ items._")
            lines.append("")
        for index, error in enumerate(check.errors, 1):
            lines += [
                f"{index}. ❌ {fmt(error.quote)}",
                f"   ✅ {fmt(error.correction)}",
                f"   💡 {fmt(error.explanation)}",
            ]

        case = cases[result.case_index]
        lines += ["", "Planted errors:"]
        labels = {"found": "FOUND", "wrong_correction": "WRONG", "missed": "MISSED"}
        for item, outcome in zip(
            case["planted"], result.planted_outcomes, strict=True
        ):
            lines.append(
                f"- [{labels[outcome]}] `{item['category']}` "
                f"`{item['wrong']}` → `{item['right']}`"
            )
        lines.append("")

    return "\n".join(lines)


async def run(args: argparse.Namespace) -> None:
    cases = load_cases(args.cases)
    settings = Settings(ollama_model=args.model)
    llm = OllamaLLM(settings)
    prompts = PromptStore(settings.prompts_dir)
    languages = ["en", "de"] if args.lang == "both" else [args.lang]
    results: list[EvalResult] = []

    try:
        for case_index, case in enumerate(cases):
            transcript = format_feedback_transcript(case["messages"])
            for lang in languages:
                for run_index in range(args.runs):
                    seed = (
                        args.seed
                        + case_index * 1000
                        + run_index * 10
                        + (0 if lang == "en" else 1)
                    )
                    label = f"{case['scenario']} {lang} run {run_index + 1}"
                    await thermal(f"before {label}", args.cool_at, args.cool_to)
                    settings.llm_seed = seed
                    prompt = prompts.feedback_prompt(transcript, lang)
                    started = time.perf_counter()
                    text = await llm.chat(
                        [{"role": "user", "content": prompt}], max_tokens=1200
                    )
                    elapsed_ms = round((time.perf_counter() - started) * 1000)
                    markdown = strip_think(text).strip()
                    check = check_feedback(
                        markdown, case["messages"], case["correct_tricky"], lang
                    )
                    outcomes = check_planted(check.errors, case["planted"])
                    results.append(
                        EvalResult(
                            case_index=case_index,
                            scenario=case["scenario"],
                            lang=lang,
                            run=run_index + 1,
                            seed=seed,
                            markdown=markdown,
                            elapsed_ms=elapsed_ms,
                            check=check,
                            planted_outcomes=outcomes,
                        )
                    )
                    print(
                        f"{label}: {elapsed_ms} ms, recall "
                        f"{sum(outcome == 'found' for outcome in outcomes)}"
                        f"/{len(outcomes)}, structure={check.structure_ok}",
                        file=sys.stderr,
                    )
    finally:
        await llm.client.aclose()

    markdown = summary_table(results, settings.ollama_model, args.seed)
    markdown += "\n" + detail_sections(results, cases) + "\n"
    print(markdown, end="")
    if args.out:
        args.out.write_text(markdown, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gemma4:26b", help="Ollama model for the eval")
    parser.add_argument("--runs", type=int, default=1, help="runs per case and language")
    parser.add_argument("--lang", choices=["en", "de", "both"], default="both")
    parser.add_argument("--seed", type=int, default=1234, help="base seed")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--cool-at", type=int, default=COOL_AT_C)
    parser.add_argument("--cool-to", type=int, default=COOL_TO_C)
    args = parser.parse_args()

    try:
        asyncio.run(run(args))
    except ThermalAbort as exc:
        print(f"ABORT: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
