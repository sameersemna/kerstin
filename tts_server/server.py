"""Kokoro German TTS sidecar with an OpenAI-compatible speech endpoint."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import torch
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from .core import (
    RequestError,
    float_to_wav,
    fix_phonemes,
    parse_voice_allowlist,
    validate_request,
)

log = logging.getLogger("kokoro_sidecar")
logging.basicConfig(level=logging.INFO, format="%(levelname)s kokoro: %(message)s")

VOICE_ROOT = Path(__file__).resolve().parents[1] / "voices" / "kokoro"


class KokoroEngine:
    def __init__(
        self,
        device: str,
        threads: int,
        root: Path = VOICE_ROOT,
        allowed_voices: tuple[str, ...] | None = None,
        idle_release_s: int = 600,
    ) -> None:
        from kokoro import KModel, KPipeline

        self.device = device
        self.threads = threads
        self.allowed_voices = set(allowed_voices or parse_voice_allowlist(None))
        self.lock = asyncio.Lock()
        self.models: dict[tuple[str, str], object] = {}
        self.voices: dict[str, tuple[object, object]] = {}
        self.gpu_resident = device == "cuda"
        self.idle_release_s = idle_release_s
        self.last_activity = time.monotonic()

        if device not in ("cpu", "cuda"):
            raise RuntimeError(f"KOKORO_DEVICE must be cpu or cuda, got {device!r}")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("KOKORO_DEVICE=cuda requested but CUDA is not available")
        if threads < 1:
            raise RuntimeError("KOKORO_THREADS must be >= 1")
        torch.set_num_threads(threads)

        for directory in sorted(root.iterdir() if root.is_dir() else []):
            config_path = directory / "config.json"
            model_path = directory / "model.pth"
            voice_path = directory / "voice.pt"
            if directory.name not in self.allowed_voices:
                continue
            if not (directory.is_dir() and config_path.is_file() and model_path.is_file() and voice_path.is_file()):
                continue
            try:
                model_key = (str(config_path), str(model_path))
                model = self.models.get(model_key)
                if model is None:
                    model = KModel(
                        repo_id="hexgrad/Kokoro-82M",
                        config=str(config_path),
                        model=str(model_path),
                    ).to(device).eval()
                    self.models[model_key] = model
                pipeline = KPipeline(lang_code="d", model=model)
                original_g2p = pipeline.g2p

                def g2p(text, original=original_g2p):
                    phonemes, tokens = original(text)
                    return fix_phonemes(phonemes), tokens

                pipeline.g2p = g2p
                voice = torch.load(voice_path, map_location="cpu", weights_only=True)
                started = time.perf_counter()
                list(pipeline("Hallo.", voice=voice, speed=1.0))
                log.info(
                    "loaded voice=%s device=%s threads=%d warmup_ms=%d",
                    directory.name,
                    device,
                    threads,
                    int((time.perf_counter() - started) * 1000),
                )
                self.voices[directory.name] = (pipeline, voice)
            except Exception as exc:  # noqa: BLE001 — one broken voice must not kill the rest
                log.error("failed voice=%s error=%s", directory.name, type(exc).__name__)

        if not self.voices:
            raise RuntimeError(f"no usable Kokoro voices under {root}")

    def _models(self) -> list[object]:
        return list(dict.fromkeys(self.models.values()))

    def _move(self, device: str) -> None:
        for model in self._models():
            model.to(device)
        self.gpu_resident = device == "cuda"
        if device == "cpu" and torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _ensure_resident(self) -> None:
        if self.device == "cuda" and not self.gpu_resident:
            before = torch.cuda.memory_allocated() / (1024 * 1024)
            started = time.perf_counter()
            self._move("cuda")
            log.info(
                "gpu reload_ms=%d vram_allocated_before_mb=%.1f",
                int((time.perf_counter() - started) * 1000),
                before,
            )

    async def synthesize(self, text: str, voice: str, speed: float) -> bytes:
        async with self.lock:
            self._ensure_resident()
            self.last_activity = time.monotonic()
            return await asyncio.to_thread(self._synthesize, text, voice, speed)

    async def warm(self) -> None:
        async with self.lock:
            self._ensure_resident()
            self.last_activity = time.monotonic()

    async def idle_loop(self) -> None:
        if self.device != "cuda" or self.idle_release_s <= 0:
            return
        while True:
            await asyncio.sleep(min(30, max(1, self.idle_release_s / 2)))
            if not self.gpu_resident:
                continue
            if time.monotonic() - self.last_activity < self.idle_release_s:
                continue
            async with self.lock:
                if not self.gpu_resident:
                    continue
                if time.monotonic() - self.last_activity < self.idle_release_s:
                    continue
                before = torch.cuda.memory_allocated() / (1024 * 1024)
                self._move("cpu")
                after = torch.cuda.memory_allocated() / (1024 * 1024)
                log.info(
                    "gpu idle release vram_before_mb=%.1f vram_after_mb=%.1f",
                    before,
                    after,
                )

    def _synthesize(self, text: str, voice: str, speed: float) -> bytes:
        started = time.perf_counter()
        pipeline, voicepack = self.voices[voice]
        chunks = [
            audio.detach().cpu().numpy() if isinstance(audio, torch.Tensor) else np.asarray(audio)
            for _, _, audio in pipeline(text, voice=voicepack, speed=speed)
        ]
        if not chunks:
            raise RuntimeError("no audio generated")
        samples = np.concatenate(chunks)
        log.info(
            "synth voice=%s chars=%d ms=%d device=%s",
            voice,
            len(text),
            int((time.perf_counter() - started) * 1000),
            self.device,
        )
        return float_to_wav(samples, rate=24000)


@asynccontextmanager
async def lifespan(app: FastAPI):
    device = os.getenv("KOKORO_DEVICE", "cpu").lower()
    threads = int(os.getenv("KOKORO_THREADS", "4"))
    try:
        app.state.engine = KokoroEngine(
            device=device,
            threads=threads,
            allowed_voices=parse_voice_allowlist(os.getenv("KOKORO_VOICES")),
            idle_release_s=int(os.getenv("KOKORO_IDLE_RELEASE_S", "600")),
        )
    except Exception as exc:
        log.error("startup failed: %s", exc)
        raise
    idle_task = asyncio.create_task(app.state.engine.idle_loop())
    try:
        yield
    finally:
        idle_task.cancel()


app = FastAPI(title="Kokoro German TTS", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    engine: KokoroEngine = app.state.engine
    return {
        "ok": True,
        "voices": sorted(engine.voices),
        "device": engine.device,
        "threads": engine.threads,
        "gpu_resident": engine.gpu_resident,
    }


@app.post("/v1/warm")
async def warm():
    engine: KokoroEngine = app.state.engine
    await engine.warm()
    return {"ok": True, "gpu_resident": engine.gpu_resident}


@app.post("/v1/audio/speech")
async def speech(request: Request):
    try:
        payload = await request.json()
        engine: KokoroEngine = app.state.engine
        parsed = validate_request(payload, engine.voices)
        wav = await engine.synthesize(parsed.text, parsed.voice, parsed.speed)
    except RequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.error("synthesis failed: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="synthesis failed") from exc
    return Response(content=wav, media_type="audio/wav")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("KOKORO_HOST", "127.0.0.1"),
        port=int(os.getenv("KOKORO_PORT", "8880")),
        log_level="info",
    )
