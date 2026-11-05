#!/usr/bin/env python3
"""Run the fixed-case hint quality eval and print a Markdown report."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import math
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from kerstin.config import PROJECT_DIR, Settings
from kerstin.hint_checks import HintCheck, check_hint
from kerstin.llm import OllamaLLM
from kerstin.prompts import PromptStore
from kerstin.text import strip_think
from smoke_test import COOL_AT_C, COOL_TO_C, ThermalAbort, cool_down

CASES_PATH = PROJECT_DIR / "scripts" / "hint_cases.json"


@dataclass(frozen=True)
class EvalResult:
    index: int
    case: dict
    seed: int
    latency_ms: int
    answer: str
    check: HintCheck


async def thermal(label: str, cool_at: int, cool_to: int) -> int:
    with contextlib.redirect_stdout(sys.stderr):
        return await cool_down(label, cool_at, cool_to)


def load_cases(path: Path) -> tuple[str, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["context"], data["cases"]


def p90(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[math.ceil(0.9 * len(ordered)) - 1]


def summary_table(results: list[EvalResult], model: str, seed: int) -> str:
    latencies = [result.latency_ms for result in results]
    passed = sum(result.check.ok for result in results)
    case_count = len({result.index for result in results})
    run_count = len(results) // case_count if case_count else 0
    lines = [
        "# Hint eval",
        "",
        f"Model: `{model}` · seed base: {seed} · cases: {case_count} · runs: {run_count}",
        "",
        "| # | query | pos | ms | format | lemma | noun/adj | example | noise | auto |",
        "|---:|---|---|---:|---|---|---|---|---:|---|",
    ]
    for result in results:
        check = result.check
        pos_check = "-" if result.case["pos"] == "verb" else ("OK" if check.pos_ok else "FAIL")
        lines.append(
            "| "
            + " | ".join(
                [
                    str(result.index),
                    result.case["query"],
                    result.case["pos"],
                    str(result.latency_ms),
                    "OK" if check.format_ok else "FAIL",
                    "OK" if check.lemma_ok else "FAIL",
                    pos_check,
                    "OK" if check.example_ok else "FAIL",
                    str(check.format_noise),
                    "PASS" if check.ok else "FAIL",
                ]
            )
            + " |"
        )
    lines += [
        "",
        (
            f"Auto checks: **{passed}/{len(results)} pass** · "
            f"p50 = **{statistics.median(latencies):.0f} ms** · "
            f"p90 = **{p90(latencies)} ms** · "
            f"mean = {statistics.mean(latencies):.0f} ms."
        ),
        "",
    ]
    return "\n".join(lines)


def detail_sections(results: list[EvalResult], context: str) -> str:
    lines = ["Neutral context:", "```text", context, "```", ""]
    for result in results:
        check = result.check
        lines += [
            (
                f"### {result.index}. {result.case['query']} "
                f"({result.case['pos']}) — {result.latency_ms} ms"
            ),
            "",
            f"Seed {result.seed} · accept: "
            + ", ".join(f"`{value}`" for value in result.case["accept"]),
            "",
            "```text",
            result.answer,
            "```",
            "",
            (
                f"format={'OK' if check.format_ok else 'FAIL'} · "
                f"lemma={'OK' if check.lemma_ok else 'FAIL'} · "
                f"pos={'OK' if check.pos_ok else 'FAIL'} · "
                f"example={'OK' if check.example_ok else 'FAIL'} · "
                f"noise={check.format_noise} · auto={'PASS' if check.ok else 'FAIL'}"
            ),
            "",
        ]
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> None:
    context, cases = load_cases(args.cases)
    settings = Settings(ollama_model=args.model)
    llm = OllamaLLM(settings)
    prompts = PromptStore(settings.prompts_dir)
    results: list[EvalResult] = []

    try:
        for index, case in enumerate(cases, 1):
            for run_index in range(args.runs):
                seed = args.seed + index + run_index * 100
                await thermal(f"before hint {index} run {run_index + 1}", args.cool_at, args.cool_to)
                settings.llm_seed = seed
                prompt = prompts.hint_prompt(case["query"], context)
                started = time.perf_counter()
                text = await llm.chat(
                    [{"role": "user", "content": prompt}],
                    max_tokens=120,
                    temperature=settings.hint_temperature,
                )
                elapsed_ms = round((time.perf_counter() - started) * 1000)
                answer = strip_think(text).strip()
                check = check_hint(answer, case)
                results.append(
                    EvalResult(
                        index=index,
                        case=case,
                        seed=seed,
                        latency_ms=elapsed_ms,
                        answer=answer,
                        check=check,
                    )
                )
                print(
                    f"hint {index} run {run_index + 1}: {elapsed_ms} ms, "
                    f"auto={'PASS' if check.ok else 'FAIL'}",
                    file=sys.stderr,
                )
    finally:
        await llm.client.aclose()

    markdown = summary_table(results, settings.ollama_model, args.seed)
    markdown += "\n" + detail_sections(results, context)
    print(markdown, end="")
    if args.out:
        args.out.write_text(markdown, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gemma4:26b", help="Ollama model for the eval")
    parser.add_argument("--runs", type=int, default=1, help="runs per case")
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
