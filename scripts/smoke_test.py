#!/usr/bin/env python3
"""Headless end-to-end smoke test for Kerstin on the GB10.

Builds one German utterance in memory with Piper, sends it over /ws and
checks transcript, reply text and audio for a few turns. No files are
written; no new dependencies are needed.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import ssl
import struct
import subprocess
import sys
import time
import wave
from urllib.parse import urlparse, urlunparse

import httpx
import numpy as np
import websockets
from kerstin.config import Settings
from piper import PiperVoice, SynthesisConfig

UTTERANCE = "Am Wochenende war ich mit Freunden am See, und das Wetter war fantastisch."
SAMPLE_RATE = 16_000
SILENCE_PAD_S = 0.3
MAX_GPU_TEMP_C = 80
TIMEOUT_FIRST_TURN_S = 60.0
TIMEOUT_LATER_TURN_S = 20.0
TIMEOUT_OPENER_S = 60.0
THINK_MARKERS = ("<think", "</think>")

_no_smi_warned = False


class SmokeError(Exception):
    """A smoke-test failure that should end the run with exit code 1."""


class ThermalAbort(Exception):
    """GPU too hot; end the run with exit code 3."""


def ms_since(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def gpu_temperature() -> int | None:
    global _no_smi_warned
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        if not _no_smi_warned:
            print("WARNING: nvidia-smi not available; continuing without thermal guard")
            _no_smi_warned = True
        return None
    lines = proc.stdout.strip().splitlines()
    if proc.returncode != 0 or not lines:
        return None
    try:
        return int(float(lines[0].strip()))
    except ValueError:
        return None


def thermal_guard(label: str) -> int | None:
    temp = gpu_temperature()
    if temp is None:
        print(f"GPU {label}: n/a")
        return None
    print(f"GPU {label}: {temp} °C")
    if temp >= MAX_GPU_TEMP_C:
        raise ThermalAbort(f"GPU at {temp} °C (limit {MAX_GPU_TEMP_C} °C)")
    return temp


def resample_linear(samples: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out or len(samples) == 0:
        return samples
    n_out = round(len(samples) / sr_in * sr_out)
    x_old = np.arange(len(samples), dtype=np.float64)
    x_new = np.linspace(0.0, len(samples) - 1.0, n_out, dtype=np.float64)
    return np.interp(x_new, x_old, samples)


def wav_to_pcm16(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        sr_in = w.getframerate()
        channels = w.getnchannels()
        width = w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if width != 2:
        raise SmokeError(f"unsupported Piper sample width: {width} bytes")
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    samples = resample_linear(samples, sr_in, SAMPLE_RATE)
    pcm = np.clip(np.round(samples), -32768, 32767).astype("<i2").tobytes()
    pad = b"\x00\x00" * int(SILENCE_PAD_S * SAMPLE_RATE)
    return pad + pcm + pad


def synthesize_utterance(settings: Settings) -> bytes:
    voice = PiperVoice.load(str(settings.piper_voice_path))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        # piper1-gpl (>=1.3) uses synthesize_wav; older piper-tts uses synthesize
        if hasattr(voice, "synthesize_wav"):
            try:
                cfg = SynthesisConfig(length_scale=settings.piper_length_scale)
                voice.synthesize_wav(UTTERANCE, wav_file, syn_config=cfg)
            except ImportError:
                voice.synthesize_wav(UTTERANCE, wav_file)
        else:
            voice.synthesize(UTTERANCE, wav_file, length_scale=settings.piper_length_scale)
    return wav_to_pcm16(buf.getvalue())


def log_message(msg: str | bytes, t0: float) -> None:
    elapsed = ms_since(t0)
    if isinstance(msg, bytes):
        if len(msg) >= 4:
            turn = struct.unpack(">I", msg[:4])[0]
            print(f"[{elapsed:6d} ms] binary turn={turn} size={len(msg)}")
        else:
            print(f"[{elapsed:6d} ms] binary size={len(msg)}")
        return
    print(f"[{elapsed:6d} ms] {msg}")


def check_reply_text(text: str) -> None:
    if any(marker in text for marker in THINK_MARKERS):
        raise SmokeError(f"reply_text contains think markup: {text!r}")


def health_url_for(ws_url: str) -> str:
    parsed = urlparse(ws_url)
    scheme = "https" if parsed.scheme == "wss" else "http"
    return urlunparse((scheme, parsed.netloc, "/health", "", "", ""))


def build_ssl_context(ws_url: str, cafile: str | None) -> ssl.SSLContext | None:
    if not ws_url.startswith("wss://"):
        return None
    if not cafile:
        raise SmokeError("wss:// requires --cafile (or KERSTIN_TLS_CA_CERTFILE)")
    return ssl.create_default_context(cafile=cafile)


def parse_text_message(msg: str) -> dict:
    try:
        data = json.loads(msg)
    except json.JSONDecodeError as exc:
        raise SmokeError(f"invalid JSON from server: {msg!r}") from exc
    if not isinstance(data, dict):
        raise SmokeError(f"unexpected JSON payload: {msg!r}")
    return data


def check_error(data: dict) -> None:
    if data.get("type") == "error":
        raise SmokeError(f"server error: {data.get('message')!r}")


async def wait_for_opener(ws) -> None:
    deadline = time.monotonic() + TIMEOUT_OPENER_S
    t0 = time.monotonic()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SmokeError(f"opener timed out after {TIMEOUT_OPENER_S:.0f} s")
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except TimeoutError as exc:
            raise SmokeError(f"opener timed out after {TIMEOUT_OPENER_S:.0f} s") from exc
        log_message(msg, t0)
        if isinstance(msg, bytes):
            continue
        data = parse_text_message(msg)
        check_error(data)
        if data.get("type") == "reply_text":
            check_reply_text(data.get("text", ""))
        if data.get("type") == "reply_done" and data.get("turn") == 0:
            return


async def run_turn(ws, turn: int, t_sent: float, timeout: float) -> tuple[dict, int]:
    deadline = t_sent + timeout
    transcript: str | None = None
    reply_texts = 0
    audio_frames = 0
    reply_done = False
    metrics: dict | None = None
    client_first_audio_ms: int | None = None

    while not (
        transcript is not None
        and reply_texts >= 1
        and audio_frames >= 1
        and reply_done
        and metrics is not None
    ):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SmokeError(
                f"turn {turn} timed out after {timeout:.0f} s "
                f"(transcript={transcript is not None}, reply_text={reply_texts}, "
                f"audio={audio_frames}, reply_done={reply_done}, "
                f"metrics={metrics is not None})"
            )
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except TimeoutError as exc:
            raise SmokeError(f"turn {turn} timed out after {timeout:.0f} s") from exc

        log_message(msg, t_sent)
        if isinstance(msg, bytes):
            if len(msg) >= 4 and struct.unpack(">I", msg[:4])[0] == turn:
                audio_frames += 1
                if client_first_audio_ms is None:
                    client_first_audio_ms = ms_since(t_sent)
            continue

        data = parse_text_message(msg)
        check_error(data)
        kind = data.get("type")

        if kind == "reply_text":
            check_reply_text(data.get("text", ""))
            if data.get("turn") == turn:
                reply_texts += 1
        elif kind == "transcript" and data.get("turn") == turn:
            transcript = data.get("text", "")
            lowered = transcript.lower()
            if "wochenende" not in lowered and "see" not in lowered:
                raise SmokeError(
                    f"turn {turn} transcript contains neither 'Wochenende' nor 'See': "
                    f"{transcript!r}"
                )
        elif kind == "reply_done" and data.get("turn") == turn:
            reply_done = True
        elif kind == "metrics" and data.get("turn") == turn:
            metrics = data

    if client_first_audio_ms is None:
        raise SmokeError(f"turn {turn} produced no client audio timestamp")
    return metrics, client_first_audio_ms


def format_temp(temp: int | None) -> str:
    return "n/a" if temp is None else f"{temp} °C"


def print_summary(rows: list[dict]) -> None:
    print("\nSummary")
    header = (
        f"{'turn':>4}  {'stt_ms':>7}  {'llm_1st_ms':>10}  {'srv_audio_ms':>12}  "
        f"{'cli_audio_ms':>12}  {'total_ms':>8}  {'gpu_before':>10}  {'gpu_after':>9}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['turn']:>4}  {row['stt_ms']:>7}  {row['llm_first_token_ms']:>10}  "
            f"{row['server_first_audio_ms']:>12}  {row['client_first_audio_ms']:>12}  "
            f"{row['total_ms']:>8}  {format_temp(row['gpu_before']):>10}  "
            f"{format_temp(row['gpu_after']):>9}"
        )


async def run(args: argparse.Namespace) -> None:
    ssl_context = build_ssl_context(args.url, args.cafile)
    health_url = health_url_for(args.url)
    async with httpx.AsyncClient(verify=ssl_context) as http:
        response = await http.get(health_url, timeout=5.0)
        print(f"GET {health_url} -> {response.status_code}")
        print(response.text)
        if response.status_code != 200:
            raise SmokeError(f"health check failed: HTTP {response.status_code}")

    settings = Settings()
    print(f"Synthesizing utterance with Piper voice {settings.piper_voice_path.name} ...")
    pcm = synthesize_utterance(settings)
    print(f"Utterance: {len(pcm) / 2 / SAMPLE_RATE:.2f} s, {len(pcm)} bytes PCM")

    rows: list[dict] = []
    async with websockets.connect(args.url, max_size=None, ssl=ssl_context) as ws:
        start: dict = {"type": "start"}
        if args.scenario:
            start["scenario"] = args.scenario
        print(f"Sending {json.dumps(start)}")
        await ws.send(json.dumps(start))
        await wait_for_opener(ws)
        print("Opener complete")

        for turn in range(1, args.turns + 1):
            gpu_before = thermal_guard(f"before turn {turn}")
            timeout = TIMEOUT_FIRST_TURN_S if turn == 1 else TIMEOUT_LATER_TURN_S
            t_sent = time.monotonic()
            await ws.send(pcm)
            metrics, client_first_audio_ms = await run_turn(ws, turn, t_sent, timeout)
            gpu_after = thermal_guard(f"after turn {turn}")
            rows.append(
                {
                    "turn": turn,
                    "stt_ms": metrics.get("stt_ms", 0),
                    "llm_first_token_ms": metrics.get("llm_first_token_ms", 0),
                    "server_first_audio_ms": metrics.get("first_audio_ms", 0),
                    "client_first_audio_ms": client_first_audio_ms,
                    "total_ms": metrics.get("total_ms", 0),
                    "gpu_before": gpu_before,
                    "gpu_after": gpu_after,
                }
            )
            print(f"Turn {turn} complete")

    thermal_guard("at end")
    print_summary(rows)


def main() -> int:
    settings = Settings()
    default_url = (
        f"wss://localhost:{settings.port}/ws"
        if settings.tls_enabled
        else f"ws://127.0.0.1:{settings.port}/ws"
    )
    default_cafile = str(settings.tls_ca_certfile) if settings.tls_ca_certfile else None
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=default_url)
    parser.add_argument("--cafile", default=default_cafile)
    parser.add_argument("--scenario", default=None, help="scenario key (default: server default)")
    parser.add_argument("--turns", type=int, default=2)
    args = parser.parse_args()

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
