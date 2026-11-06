#!/usr/bin/env python3
"""Calibration eval for the exam rubric estimate (text only, real Ollama)."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from pathlib import Path

from kerstin.config import BACKEND_DIR, Settings
from kerstin.exam import MODERATION_PREFIX, ExamPart, ExamPlan
from kerstin.llm import OllamaLLM
from kerstin.prompts import PromptStore
from kerstin.score import (
    BANDS,
    CRITERIA,
    ExamScore,
    learner_text,
    parse_score,
    score_prompt,
)
from kerstin.text import strip_think
from smoke_test import COOL_AT_C, COOL_TO_C, ThermalAbort, cool_down

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "scripts" / "score_cases.json"
VARIANTS = ("orig", "drop", "noisy")


def _noisy(text: str) -> str:
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    words = text.split()
    if not words:
        return ""
    first = words[0][:1].upper() + words[0][1:].lower()
    return " ".join([first, *(word.lower() for word in words[1:])])


def _plan(case: dict, topic: dict) -> ExamPlan:
    card = topic["card"]
    return ExamPlan(
        preset="vortrag_diskussion",
        title="Vortrag und Diskussion",
        note="Angelehnt an gängige B2-Prüfungsformate – keine offizielle Prüfung.",
        greeting="Hallo.",
        parts=[
            ExamPart("prep", "Vorbereitung", 300, "Bereite deinen Vortrag vor.", card),
            ExamPart("learner_talk", "Dein Kurzvortrag", 240, "Halte deinen Vortrag.", card),
            ExamPart(
                "kerstin_talk",
                "Kerstins Kurzvortrag",
                150,
                "Kerstin hält ihren Vortrag.",
                {"title": "Kerstins Vortrag"},
            ),
            ExamPart(
                "dialog",
                "Diskussion",
                300,
                "Diskutiert das Thema.",
                {"question": topic["question"], "aspects": []},
            ),
        ],
    )


def _history(case: dict, topic: dict, variant: str) -> list[dict]:
    talk = list(case["talk"])
    discussion = list(case["discussion"])
    if variant == "drop":
        discussion = discussion[:-1]
    if variant == "noisy":
        talk = [_noisy(line) for line in talk]
        discussion = [_noisy(line) for line in discussion]

    history = [
        {"role": "assistant", "content": "Hallo."},
        {
            "role": "user",
            "content": f"{MODERATION_PREFIX}Teil 2 – Dein Kurzvortrag",
        },
        *[{"role": "user", "content": line} for line in talk],
        {"role": "user", "content": f"{MODERATION_PREFIX}Teil 4 – Diskussion"},
    ]
    for kerstin, learner in zip(topic["kerstin"], discussion):
        history.append({"role": "assistant", "content": kerstin})
        history.append({"role": "user", "content": learner})
    return history


async def _score_once(
    llm: OllamaLLM,
    prompt: str,
    learner: str,
    label: str,
    args: argparse.Namespace,
) -> tuple[ExamScore | None, int, int]:
    last_ms = 0
    for attempt in (1, 2):
        await cool_down(f"{label} attempt {attempt}", args.cool_at, args.cool_to)
        started = time.perf_counter()
        try:
            raw = await llm.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=700,
                temperature=0.0,
                model=args.model,
                fmt="json",
                seed=args.seed,
            )
        except Exception as exc:  # noqa: BLE001 — retry transport failures once
            last_ms = int((time.perf_counter() - started) * 1000)
            print(f"{label} attempt {attempt} error {type(exc).__name__}")
            continue
        last_ms = int((time.perf_counter() - started) * 1000)
        parsed = parse_score(strip_think(raw).strip(), learner)
        if parsed is not None:
            return parsed, last_ms, attempt
    return None, last_ms, 2


def _bands(score: ExamScore | None) -> list[int] | None:
    return None if score is None else [criterion.band for criterion in score.criteria]


def _mean(score: ExamScore | None) -> float | None:
    bands = _bands(score)
    return None if bands is None else sum(bands) / len(bands)


def _by_key(score: ExamScore | None, key: str) -> int | None:
    if score is None:
        return None
    return next(criterion.band for criterion in score.criteria if criterion.key == key)


def _check(label: str, ok: bool, detail: str) -> bool:
    print(f"{label}: {'PASS' if ok else 'FAIL'} — {detail}")
    return ok


async def run(args: argparse.Namespace) -> int:
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    settings = Settings(ollama_model=args.model, score_seed=args.seed)
    store = PromptStore(BACKEND_DIR / "prompts")
    llm = OllamaLLM(settings)
    results: dict[str, dict[str, ExamScore | None]] = {}
    latencies: list[int] = []
    attempts: list[int] = []
    failures: list[str] = []

    print(f"Model: {args.model} | seed: {args.seed} | variants: {', '.join(VARIANTS)}")
    print(f"Cases: {len(data['cases'])} | cool_down: {args.cool_at}→{args.cool_to} °C")

    try:
        for case in data["cases"]:
            topic = data["topics"][case["topic"]]
            plan = _plan(case, topic)
            results[case["id"]] = {}
            for variant in VARIANTS:
                history = _history(case, topic, variant)
                prompt = score_prompt(store, history, plan, "en")
                learner = learner_text(history)
                label = f"{case['id']} {variant}"
                parsed, elapsed_ms, attempt = await _score_once(
                    llm, prompt, learner, label, args
                )
                results[case["id"]][variant] = parsed
                latencies.append(elapsed_ms)
                attempts.append(attempt)
                if parsed is None:
                    print(f"{case['id']:20} {variant:5} parse=FAIL ms={elapsed_ms}")
                    continue
                bands = _bands(parsed)
                extra = (
                    f" density={parsed.error_density} errors={parsed.grammar_errors}"
                    if variant == "orig"
                    else ""
                )
                print(
                    f"{case['id']:20} {variant:5} "
                    f"bands={bands} overall={parsed.overall_band} "
                    f"ms={elapsed_ms} dropped={parsed.dropped_evidence} "
                    f"attempt={attempt}{extra}"
                )
    finally:
        await llm.client.aclose()

    parsed_count = sum(
        1
        for variants in results.values()
        for score in variants.values()
        if score is not None
    )
    if not _check("parse", parsed_count == 30, f"{parsed_count}/30 parsed"):
        failures.append("parse")

    topic_order = True
    topic_details = []
    for topic_name, topic in data["topics"].items():
        levels = {
            level: _mean(results.get(f"{topic_name}_{level}", {}).get("orig"))
            for level in ("B1", "B2", "C1")
        }
        ok = all(value is not None for value in levels.values()) and (
            levels["B1"] < levels["B2"] < levels["C1"]
        )
        topic_order = topic_order and ok
        topic_details.append(
            f"{topic_name} B1={levels['B1']} B2={levels['B2']} C1={levels['C1']}"
        )
    if not _check("order", topic_order, "; ".join(topic_details)):
        failures.append("order")

    level_cases = {
        "B1": [case["id"] for case in data["cases"] if case["level"] == "B1"],
        "B2": [
            case["id"]
            for case in data["cases"]
            if case["level"] == "B2" and not case["id"].endswith("_offtask")
        ],
        "C1": [case["id"] for case in data["cases"] if case["level"] == "C1"],
    }
    level_means = {
        level: {case_id: _mean(results[case_id]["orig"]) for case_id in case_ids}
        for level, case_ids in level_cases.items()
    }
    levels_ok = (
        all(
            mean is not None and mean <= 1.75
            for mean in level_means["B1"].values()
        )
        and all(
            mean is not None and 2.0 <= mean <= 3.25
            for mean in level_means["B2"].values()
        )
        and all(
            mean is not None and mean >= 3.25
            for mean in level_means["C1"].values()
        )
    )
    level_detail = "; ".join(
        f"{level}="
        + ", ".join(f"{case}:{mean}" for case, mean in means.items())
        for level, means in level_means.items()
    )
    if not _check("levels", levels_ok, level_detail):
        failures.append("levels")

    overall_cases = {
        "B1": level_cases["B1"],
        "B2": level_cases["B2"],
        "C1": level_cases["C1"],
    }
    overall_ok = (
        all(
            results[case_id]["orig"] is not None
            and results[case_id]["orig"].overall_band == 1
            for case_id in overall_cases["B1"]
        )
        and all(
            results[case_id]["orig"] is not None
            and results[case_id]["orig"].overall_band in (2, 3)
            for case_id in overall_cases["B2"]
        )
        and all(
            results[case_id]["orig"] is not None
            and results[case_id]["orig"].overall_band >= 3
            for case_id in overall_cases["C1"]
        )
    )
    overall_detail = "; ".join(
        f"{case_id}:{None if results[case_id]['orig'] is None else results[case_id]['orig'].overall_band}"
        for case_ids in overall_cases.values()
        for case_id in case_ids
    )
    if not _check("overall", overall_ok, overall_detail):
        failures.append("overall")

    off = results["wohnen_B2_offtask"]["orig"]
    on = results["wohnen_B2"]["orig"]
    off_task = _by_key(off, "aufgabe")
    on_task = _by_key(on, "aufgabe")
    off_words = _by_key(off, "wortschatz")
    on_words = _by_key(on, "wortschatz")
    off_grammar = _by_key(off, "grammatik")
    on_grammar = _by_key(on, "grammatik")
    off_ok = (
        off_task is not None
        and on_task is not None
        and off_task <= 2
        and off_task <= on_task - 1
        and off_words is not None
        and on_words is not None
        and abs(off_words - on_words) <= 1
        and off_grammar is not None
        and on_grammar is not None
        and abs(off_grammar - on_grammar) <= 1
    )
    if not _check(
        "offtask",
        off_ok,
        f"aufgabe={off_task}/{on_task} wortschatz={off_words}/{on_words} "
        f"grammatik={off_grammar}/{on_grammar}",
    ):
        failures.append("offtask")

    spread_ok = True
    widest = 0
    for case in data["cases"]:
        for criterion in CRITERIA:
            values = [
                _by_key(results[case["id"]][variant], criterion)
                for variant in VARIANTS
            ]
            if any(value is None for value in values):
                spread_ok = False
                continue
            spread = max(values) - min(values)
            widest = max(widest, spread)
            if spread > 1:
                spread_ok = False
    stable_cases = 0
    for case in data["cases"]:
        overall = [
            results[case["id"]][variant].overall_band
            for variant in VARIANTS
            if results[case["id"]][variant] is not None
        ]
        if overall and max(overall.count(value) for value in set(overall)) >= 2:
            stable_cases += 1
    stability_ok = spread_ok and stable_cases >= 9
    if not _check(
        "stability",
        stability_ok,
        f"max criterion spread={widest}; overall stable in {stable_cases}/10 cases",
    ):
        failures.append("stability")

    evidence_total = 30 * len(CRITERIA)
    evidence_dropped = sum(
        score.dropped_evidence
        for variants in results.values()
        for score in variants.values()
        if score is not None
    )
    evidence_ratio = evidence_dropped / evidence_total
    if not _check(
        "evidence",
        evidence_ratio <= 0.10,
        f"{evidence_dropped}/{evidence_total} dropped ({evidence_ratio:.1%})",
    ):
        failures.append("evidence")

    p50 = int(statistics.median(latencies)) if latencies else 0
    print(f"latency: p50={p50} ms max={max(latencies) if latencies else 0} ms")
    print(f"retries: {sum(1 for attempt in attempts if attempt == 2)} calls needed a retry")

    print("\nOrig reasons and evidence")
    for case in data["cases"]:
        score = results[case["id"]]["orig"]
        print(f"\n{case['id']} ({case['level']}):")
        if score is None:
            print("  parse FAIL")
            continue
        print(f"  overall: {score.overall_band} ({BANDS[score.overall_band]})")
        for criterion in score.criteria:
            print(
                f"  {criterion.label}: {criterion.band} "
                f"({criterion.band_label}) — {criterion.reason} "
                f"[{criterion.evidence!r}]"
            )

    if failures:
        print(f"\nFAILURES: {failures}")
        return 1
    print("\nAll score checks passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gemma4:26b", help="Ollama model")
    parser.add_argument("--seed", type=int, default=7, help="fixed scoring seed")
    parser.add_argument("--cool-at", type=float, default=COOL_AT_C)
    parser.add_argument("--cool-to", type=float, default=COOL_TO_C)
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except ThermalAbort as exc:
        print(f"ABORT: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
