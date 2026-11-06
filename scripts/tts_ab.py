#!/usr/bin/env python3
"""TTS A/B: Piper vs Kokoro German voices (latency, resources, WER)."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
import re
import secrets
import subprocess
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
from kerstin.config import Settings
from kerstin.stt import make_stt
from kerstin.tts import PiperTTS

ROOT = Path(__file__).resolve().parents[1]
SENTENCES_PATH = ROOT / "scripts" / "tts_sentences.json"
LISTEN_IDS = ("s02", "s09", "s13", "s17", "s20", "s22", "s25", "s27", "s29")
SPOT_IDS = ("s02", "s13", "s27")


def normalise(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def wer(reference: str, hypothesis: str) -> float:
    ref = normalise(reference).split()
    hyp = normalise(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 1.0
    previous = list(range(len(hyp) + 1))
    for index, ref_word in enumerate(ref, 1):
        current = [index]
        for column, hyp_word in enumerate(hyp, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (ref_word != hyp_word),
                )
            )
        previous = current
    return previous[-1] / len(ref)


def wav_info(data: bytes) -> tuple[int, float]:
    with wave.open(io.BytesIO(data), "rb") as wav:
        return wav.getframerate(), wav.getnframes() / wav.getframerate()


def wav_to_pcm16_16k(data: bytes) -> bytes:
    with wave.open(io.BytesIO(data), "rb") as wav:
        rate = wav.getframerate()
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        raw = wav.readframes(wav.getnframes())
    if width != 2 or channels != 1:
        raise ValueError("expected 16-bit mono WAV")
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    if rate != 16000:
        count = round(len(samples) * 16000 / rate)
        samples = np.interp(
            np.linspace(0, len(samples) - 1, count, endpoint=True),
            np.arange(len(samples)),
            samples,
        )
    return samples.astype("<i2").tobytes()


def percentile(values: list[float], value: float) -> float:
    return float(np.percentile(values, value)) if values else 0.0


def _proc_rss_kb(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        pass
    return 0


def _proc_ticks(pid: int) -> int:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().split()
        return int(fields[13]) + int(fields[14])
    except (OSError, IndexError, ValueError):
        return 0


def _gpu_temp_util() -> tuple[int, int]:
    try:
        raw = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"],
            text=True,
            timeout=2,
        ).splitlines()[0]
        util, temp = (int(value.strip()) for value in raw.split(","))
        return util, temp
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0, 0


def _gpu_pid_vram(pid: int) -> int:
    try:
        raw = subprocess.check_output(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
            text=True,
            timeout=2,
        )
        for line in raw.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) == 2 and parts[0] == str(pid):
                return int(float(parts[1]))
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0
    return 0


@dataclass
class Resources:
    rss_peak_kb: int = 0
    cpu_percent: float = 0.0
    vram_idle_mb: int = 0
    vram_peak_mb: int = 0
    gpu_util_peak: int = 0
    gpu_temp_peak: int = 0


class Sampler:
    def __init__(self, pid: int | None, gpu: bool) -> None:
        self.pid = pid
        self.gpu = gpu
        self.resources = Resources()
        self._stop = asyncio.Event()
        self._start_ticks = 0
        self._start_time = 0.0
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self.pid:
            self.resources.vram_idle_mb = _gpu_pid_vram(self.pid)
            self._start_ticks = _proc_ticks(self.pid)
            self._start_time = time.monotonic()
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while not self._stop.is_set():
            if self.pid:
                self.resources.rss_peak_kb = max(
                    self.resources.rss_peak_kb, _proc_rss_kb(self.pid)
                )
                self.resources.vram_peak_mb = max(
                    self.resources.vram_peak_mb, _gpu_pid_vram(self.pid)
                )
            if self.gpu:
                util, temp = _gpu_temp_util()
                self.resources.gpu_util_peak = max(self.resources.gpu_util_peak, util)
                self.resources.gpu_temp_peak = max(self.resources.gpu_temp_peak, temp)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)
            except TimeoutError:
                pass

    async def stop(self) -> Resources:
        self._stop.set()
        if self._task:
            await self._task
        if self.pid and self._start_time:
            elapsed = time.monotonic() - self._start_time
            ticks = _proc_ticks(self.pid) - self._start_ticks
            self.resources.cpu_percent = ticks / os.sysconf("SC_CLK_TCK") / elapsed * 100
        return self.resources


@dataclass
class Measured:
    engine: str
    voice: str
    kind: str
    synth_ms: float
    audio_ms: float


async def _piper_engine(settings: Settings, sentences: list[dict], runs: int, warmup: int) -> tuple[list[Measured], list[str]]:
    piper = PiperTTS(settings)
    measured = []
    hashes = []
    for sentence in sentences:
        if warmup:
            await piper.synthesize(sentence["text"])
        for _ in range(runs):
            started = time.perf_counter()
            data = await piper.synthesize(sentence["text"])
            elapsed = (time.perf_counter() - started) * 1000
            _, audio_s = wav_info(data)
            measured.append(
                Measured("piper", "thorsten-medium", sentence["kind"], elapsed, audio_s * 1000)
            )
        if sentence["id"] in SPOT_IDS:
            hashes.append(f"{sentence['id']}:{hashlib.sha256(data).hexdigest()[:16]}")
    return measured, hashes


async def _kokoro_engine(
    client: httpx.AsyncClient,
    url: str,
    voice: str,
    sentences: list[dict],
    runs: int,
    warmup: int,
) -> tuple[list[Measured], list[str]]:
    measured = []
    hashes = []
    for sentence in sentences:
        if warmup:
            await _kokoro_call(client, url, voice, sentence["text"])
        for _ in range(runs):
            started = time.perf_counter()
            data = await _kokoro_call(client, url, voice, sentence["text"])
            elapsed = (time.perf_counter() - started) * 1000
            _, audio_s = wav_info(data)
            measured.append(
                Measured("kokoro", voice, sentence["kind"], elapsed, audio_s * 1000)
            )
        if sentence["id"] in SPOT_IDS:
            hashes.append(f"{sentence['id']}:{hashlib.sha256(data).hexdigest()[:16]}")
    return measured, hashes


async def _kokoro_call(client: httpx.AsyncClient, url: str, voice: str, text: str) -> bytes:
    response = await client.post(
        f"{url.rstrip('/')}/v1/audio/speech",
        json={
            "model": "kokoro",
            "voice": voice,
            "input": text,
            "response_format": "wav",
            "speed": 1.0,
        },
    )
    response.raise_for_status()
    return response.content


def _markdown_latency(all_measured: list[Measured], device: str) -> None:
    print("\n### Latency")
    print("| engine | voice | device | kind | n | p50 ms | p90 ms | RTF p50 |")
    print("|---|---|---|---|---:|---:|---:|---:|")
    groups: dict[tuple[str, str, str], list[Measured]] = {}
    for item in all_measured:
        groups.setdefault((item.engine, item.voice, item.kind), []).append(item)
    for (engine, voice, kind), items in sorted(groups.items()):
        values = [item.synth_ms for item in items]
        rtf = [item.synth_ms / item.audio_ms for item in items if item.audio_ms]
        print(
            f"| {engine} | {voice} | {device} | {kind} | {len(values)} | "
            f"{percentile(values, 50):.1f} | {percentile(values, 90):.1f} | "
            f"{percentile(rtf, 50):.3f} |"
        )


def _markdown_resources(rows: list[tuple[str, str, Resources]], device: str) -> None:
    print("\n### Resources")
    print("| engine | voice | device | RSS MB | CPU % | VRAM idle/peak MB | GPU util % | peak °C |")
    print("|---|---|---|---:|---:|---:|---:|---:|")
    for engine, voice, resource in rows:
        print(
            f"| {engine} | {voice} | {device} | {resource.rss_peak_kb / 1024:.0f} | "
            f"{resource.cpu_percent:.0f} | {resource.vram_idle_mb}/{resource.vram_peak_mb} | "
            f"{resource.gpu_util_peak} | {resource.gpu_temp_peak} |"
        )


async def _asr_roundtrip(
    engine_name: str,
    synthesize,
    sentences: list[dict],
) -> tuple[float, list[tuple[str, str, str, float]]]:
    stt = make_stt(Settings())
    scores = []
    diffs = []
    for sentence in sentences:
        data = await synthesize(sentence["text"])
        transcript = await stt.transcribe(wav_to_pcm16_16k(data))
        score = wer(sentence["text"], transcript)
        scores.append(score)
        if normalise(sentence["text"]) != normalise(transcript):
            diffs.append((sentence["id"], sentence["text"], transcript, score))
    return sum(scores) / len(scores) if scores else 0.0, diffs


async def run(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.sentences).read_text(encoding="utf-8"))
    sentences = data["sentences"]
    settings = Settings()
    results: list[Measured] = []
    resources: list[tuple[str, str, Resources]] = []
    hashes: list[str] = []
    wer_rows: list[tuple[str, float]] = []

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        health = (await client.get(f"{args.kokoro_url.rstrip('/')}/health")).json()
        voices = health.get("voices", [])
        print(f"device={args.device_label} kokoro_threads={health.get('threads')} voices={voices}")

        if not args.no_piper:
            sampler = Sampler(None, False)
            await sampler.start()
            measured, piper_hashes = await _piper_engine(settings, sentences, args.runs, args.warmup)
            resource = await sampler.stop()
            results.extend(measured)
            resources.append(("piper", "thorsten-medium", resource))
            hashes.extend(f"piper {item}" for item in piper_hashes)
            if args.asr:
                piper = PiperTTS(settings)
                mean_wer, diffs = await _asr_roundtrip(
                    "piper", lambda text: piper.synthesize(text), sentences
                )
                wer_rows.append(("piper/thorsten-medium", mean_wer))
                for item in diffs:
                    print(f"ASR-DIFF piper {item[0]} ref={item[1]!r} hyp={item[2]!r} wer={item[3]:.3f}")

        for voice in voices:
            sampler = Sampler(args.sidecar_pid, args.gpu)
            await sampler.start()
            measured, voice_hashes = await _kokoro_engine(
                client, args.kokoro_url, voice, sentences, args.runs, args.warmup
            )
            resource = await sampler.stop()
            results.extend(measured)
            resources.append(("kokoro", voice, resource))
            hashes.extend(f"{voice} {item}" for item in voice_hashes)
            if args.asr:
                mean_wer, diffs = await _asr_roundtrip(
                    voice,
                    lambda text, v=voice: _kokoro_call(client, args.kokoro_url, v, text),
                    sentences,
                )
                wer_rows.append((f"kokoro/{voice}", mean_wer))
                for item in diffs:
                    print(f"ASR-DIFF {voice} {item[0]} ref={item[1]!r} hyp={item[2]!r} wer={item[3]:.3f}")

        if args.out:
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            key = {}
            piper = PiperTTS(settings)
            for engine_name, synthesize in [
                ("piper", None),
                *[(voice, voice) for voice in voices],
            ]:
                for sentence in sentences:
                    if sentence["id"] not in LISTEN_IDS:
                        continue
                    if engine_name == "piper":
                        data = await piper.synthesize(sentence["text"])
                    else:
                        data = await _kokoro_call(client, args.kokoro_url, synthesize, sentence["text"])
                    token = secrets.token_hex(6)
                    (out / f"{token}.wav").write_bytes(data)
                    key[token] = {"engine": engine_name, "id": sentence["id"]}
            (out / "key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
            print(f"listening pack: {out} ({len(key)} files + key.json)")

    _markdown_latency(results, args.device_label)
    _markdown_resources(resources, args.device_label)
    if wer_rows:
        print("\n### ASR round-trip WER")
        print("| engine | mean WER |")
        print("|---|---:|")
        for engine_name, score in wer_rows:
            print(f"| {engine_name} | {score:.3f} |")
    print("\n### Spot hashes (compare across devices)")
    for line in hashes:
        print(line)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sentences", default=str(SENTENCES_PATH))
    parser.add_argument("--kokoro-url", default="http://127.0.0.1:8880")
    parser.add_argument("--sidecar-pid", type=int, default=None)
    parser.add_argument("--device-label", default="cpu4")
    parser.add_argument("--threads", type=int, default=0, help="informational; server owns threads")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--no-piper", action="store_true")
    parser.add_argument("--asr", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--gpu", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
