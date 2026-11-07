#!/usr/bin/env python3
"""Per-stage latency baseline over the WebSocket, plus a VAD-tail estimate.

Measures only; it does not tune or optimize anything. Run against a live
server on 8771 (see `make bench`). Prints tables to stdout, writes no files.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import struct
import sys
import time

import httpx
import numpy as np
import websockets
from kerstin.config import Settings
from smoke_test import (
    COOL_AT_C,
    COOL_TO_C,
    TIMEOUT_FIRST_TURN_S,
    TIMEOUT_LATER_TURN_S,
    SmokeError,
    ThermalAbort,
    build_ssl_context,
    check_error,
    check_reply_text,
    cool_down,
    health_url_for,
    parse_text_message,
    synthesize_utterance,
    wait_for_opener,
)

VAD_TAIL_MS = 768

UTTERANCES = [
    "Ich wohne seit drei Jahren in Berlin.",
    "Am Wochenende fahre ich oft mit dem Fahrrad an der Spree entlang.",
    "Was machst du eigentlich in deiner Freizeit, wenn du nicht arbeitest?",
    "Meine Lieblingsstadt in Deutschland ist Hamburg, weil sie direkt am Wasser liegt.",
    "Ich habe letzte Woche einen Deutschkurs angefangen, der mir sehr gut gefällt.",
    "Wenn ich am Abend nach Hause komme, koche ich meistens etwas Einfaches und höre dabei Musik.",
    "Kannst du mir vielleicht ein paar Tipps geben, wie ich meinen Wortschatz besser erweitern kann?",
    (
        "Obwohl das Wetter am Sonntag ziemlich schlecht war, sind wir mit Freunden in den Park "
        "gegangen und haben dort ein Picknick gemacht."
    ),
    (
        "Ich interessiere mich sehr für Geschichte und würde deshalb gern einmal nach Dresden "
        "fahren, um die alten Gebäude und Museen zu besichtigen."
    ),
    (
        "In meiner Heimatstadt gibt es einen großen Markt, auf dem man frische Produkte kaufen "
        "kann, und am Wochenende treffen sich dort viele Menschen, um miteinander zu sprechen "
        "oder etwas zu essen."
    ),
]

METRICS = [
    ("audio_s", "audio_s", "f"),
    ("stt_ms", "stt_ms", "i"),
    ("stt_wait_ms", "stt_wait_ms", "i"),
    ("llm_first_token_ms", "llm_first_token_ms", "i"),
    ("first_sentence_ms", "first_sentence_ms", "i"),
    ("tts_first_ms", "tts_first_ms", "i"),
    ("first_audio_ms", "first_audio_ms", "i"),
    ("total_ms", "total_ms", "i"),
    ("sentences", "sentences", "i"),
]


def percentile(values: list[float], p: float) -> float:
    return float(np.percentile(values, p))


async def run_turn(
    ws,
    turn: int,
    pcm: bytes,
    timeout: float,
    *,
    early_stt: bool = False,
    vad_tail_ms: int = VAD_TAIL_MS,
) -> dict:
    if early_stt:
        await ws.send(b"KDR1" + struct.pack("<I", turn) + pcm)
        await asyncio.sleep(max(0, vad_tail_ms - 192) / 1000)
        await ws.send(json.dumps({"type": "commit", "draft": turn}))

    t_sent = time.monotonic()
    deadline = t_sent + timeout
    await ws.send(pcm)

    transcript: str | None = None
    replies: list[str] = []
    got_audio = False
    reply_done = False
    metrics: dict | None = None

    while not (
        transcript is not None and replies and got_audio and reply_done and metrics is not None
    ):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SmokeError(f"turn {turn} timed out after {timeout:.0f} s")
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except TimeoutError as exc:
            raise SmokeError(f"turn {turn} timed out after {timeout:.0f} s") from exc

        if isinstance(msg, bytes):
            if len(msg) >= 4 and struct.unpack(">I", msg[:4])[0] == turn:
                got_audio = True
            continue

        data = parse_text_message(msg)
        check_error(data)
        kind = data.get("type")
        if kind == "stt_empty" and data.get("turn") == turn:
            raise SmokeError(f"turn {turn}: stt_empty")
        if kind == "reply_text":
            check_reply_text(data.get("text", ""))
            if data.get("turn") == turn:
                replies.append(data.get("text", ""))
        elif kind == "transcript" and data.get("turn") == turn:
            transcript = data.get("text", "")
        elif kind == "reply_done" and data.get("turn") == turn:
            reply_done = True
        elif kind == "metrics" and data.get("turn") == turn:
            metrics = data

    if transcript is None or metrics is None:
        raise SmokeError(f"turn {turn} finished without transcript/metrics")
    result = dict(metrics)
    result["transcript"] = transcript
    result["reply"] = " ".join(replies)
    result["draft_sent"] = early_stt
    return result


def print_metric_table(rows: list[dict]) -> None:
    print(f"\n(a) Server metrics (n={len(rows)})")
    print(f"{'metric':<22}{'p50':>10}{'p90':>10}{'max':>10}")
    print("-" * 52)
    for key, label, kind in METRICS:
        values = [float(row[key]) for row in rows]
        p50 = percentile(values, 50)
        p90 = percentile(values, 90)
        maximum = max(values)
        if kind == "f":
            print(f"{label:<22}{p50:>10.2f}{p90:>10.2f}{maximum:>10.2f}")
        else:
            print(f"{label:<22}{p50:>10.0f}{p90:>10.0f}{maximum:>10.0f}")


def print_stage_table(rows: list[dict]) -> None:
    stages = {
        "stt": [row["stt_ms"] for row in rows],
        "llm_to_first_token": [row["llm_first_token_ms"] - row["stt_ms"] for row in rows],
        "first_sentence_wait": [
            row["first_sentence_ms"] - row["llm_first_token_ms"] for row in rows
        ],
        "tts_first": [row["tts_first_ms"] for row in rows],
    }
    print("\n(b) Derived stages (ms)")
    print(f"{'stage':<22}{'p50':>10}{'p90':>10}")
    print("-" * 42)
    for name, values in stages.items():
        p50 = percentile([float(v) for v in values], 50)
        p90 = percentile([float(v) for v in values], 90)
        print(f"{name:<22}{p50:>10.0f}{p90:>10.0f}")


def print_early_stt(rows: list[dict]) -> None:
    sent = sum(1 for row in rows if row.get("draft_sent"))
    used = sum(1 for row in rows if row.get("stt_early") is True)
    wasted = sent - used
    turns = max(1, len(rows))
    print("\n(e) Early STT (inferred from per-turn stt_early)")
    print(
        f"    drafts sent: {sent}  committed by client: {sent}  "
        f"used: {used}  wasted STT: {wasted}"
    )
    print(
        f"    per turn: drafts {sent / turns:.2f}  committed {sent / turns:.2f}  "
        f"wasted STT {wasted / turns:.2f}"
    )


def print_estimate(rows: list[dict], vad_tail_ms: int) -> None:
    estimates = [row["first_audio_ms"] + vad_tail_ms for row in rows]
    p50 = percentile([float(v) for v in estimates], 50)
    p90 = percentile([float(v) for v in estimates], 90)
    print(
        f"\n(c) Estimated end-of-speech -> first audio "
        f"(first_audio_ms + {vad_tail_ms} ms VAD tail)"
    )
    print(f"    p50: {p50:.0f} ms    p90: {p90:.0f} ms    target: 1500 ms")
    print(f"    vs target: p50 {p50 - 1500:+.0f} ms    p90 {p90 - 1500:+.0f} ms")


def print_turns(rows: list[dict]) -> None:
    print("\n(d) Turns: transcript -> reply")
    for index, row in enumerate(rows, 1):
        transcript = row["transcript"].replace("\n", " ")
        reply = row["reply"].replace("\n", " ")
        print(f"{index:2d}. {transcript} -> {reply}")


def default_url(settings: Settings) -> str:
    if settings.tls_enabled:
        return f"wss://localhost:{settings.port}/ws"
    return f"ws://127.0.0.1:{settings.port}/ws"


async def run(args: argparse.Namespace) -> None:
    settings = Settings()
    ssl_context = build_ssl_context(args.url, args.cafile)
    health_url = health_url_for(args.url)
    async with httpx.AsyncClient(verify=ssl_context) as http:
        response = await http.get(health_url, timeout=5.0)
        print(f"GET {health_url} -> {response.status_code}")
        print(response.text)
        if response.status_code != 200:
            raise SmokeError(f"health check failed: HTTP {response.status_code}")

    print(f"Synthesizing {len(UTTERANCES)} utterances with Piper ...")
    pcms = [synthesize_utterance(settings, text) for text in UTTERANCES]
    durations = [len(pcm) / 2 / 16000 for pcm in pcms]
    print("Utterance durations (s): " + ", ".join(f"{d:.2f}" for d in durations))

    pause = max(1.0, args.pause)
    gpu_start = await cool_down("at start", args.cool_at, args.cool_to)
    measured: list[dict] = []
    turn = 0
    total_turns = args.warmup + args.runs * len(UTTERANCES)

    async with websockets.connect(args.url, max_size=None, ssl=ssl_context) as ws:
        await ws.send(json.dumps({"type": "start"}))
        await wait_for_opener(ws, verbose=False)
        print("Opener complete")

        for index in range(args.warmup):
            turn += 1
            await cool_down(
                f"before warmup {index + 1}/{args.warmup}",
                args.cool_at,
                args.cool_to,
            )
            await run_turn(
                ws,
                turn,
                pcms[0],
                TIMEOUT_FIRST_TURN_S,
                early_stt=args.early_stt,
                vad_tail_ms=args.vad_tail_ms,
            )
            await asyncio.sleep(pause)

        for _ in range(args.runs):
            for text_index, pcm in enumerate(pcms):
                turn += 1
                await cool_down(
                    f"before turn {turn}/{total_turns}",
                    args.cool_at,
                    args.cool_to,
                )
                timeout = TIMEOUT_FIRST_TURN_S if turn == 1 else TIMEOUT_LATER_TURN_S
                row = await run_turn(
                    ws,
                    turn,
                    pcm,
                    timeout,
                    early_stt=args.early_stt,
                    vad_tail_ms=args.vad_tail_ms,
                )
                measured.append(row)
                print(
                    f"  turn {turn:2d}/{total_turns} ({text_index + 1}/{len(UTTERANCES)}): "
                    f"{row['audio_s']:.2f} s audio, first_audio {row['first_audio_ms']} ms"
                )
                await asyncio.sleep(pause)

    gpu_end = await cool_down("at end", args.cool_at, args.cool_to)
    print_metric_table(measured)
    print_stage_table(measured)
    if args.early_stt:
        print_early_stt(measured)
    print_estimate(measured, args.vad_tail_ms)
    print_turns(measured)
    print(f"\n(f) GPU: start {gpu_start} °C, end {gpu_end} °C")


def main() -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=default_url(settings))
    parser.add_argument(
        "--cafile",
        default=str(settings.tls_ca_certfile) if settings.tls_ca_certfile else None,
    )
    parser.add_argument("--runs", type=int, default=2, help="passes over the utterance list")
    parser.add_argument("--warmup", type=int, default=1, help="unmeasured turns before measuring")
    parser.add_argument("--pause", type=float, default=1.5, help="seconds between turns (>= 1)")
    parser.add_argument("--cool-at", type=int, default=COOL_AT_C)
    parser.add_argument("--cool-to", type=int, default=COOL_TO_C)
    parser.add_argument("--vad-tail-ms", type=int, default=VAD_TAIL_MS)
    parser.add_argument(
        "--early-stt",
        action="store_true",
        help="send a draft 192 ms into the pause, then commit + final at the tail end",
    )
    args = parser.parse_args()

    if args.runs < 1:
        parser.error("--runs must be >= 1")
    if args.warmup < 0:
        parser.error("--warmup must be >= 0")

    try:
        asyncio.run(run(args))
    except ThermalAbort as exc:
        print(f"ABORT: {exc}")
        return 3
    except SmokeError as exc:
        print(f"FAIL: {exc}")
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
