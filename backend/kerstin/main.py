"""FastAPI app: serves the browser client and the /ws conversation endpoint.

Run:  cd backend && uvicorn kerstin.main:app --host 127.0.0.1 --port 8770
(or `make run` from the project root)
"""

from __future__ import annotations

import json
import logging
import random
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import settings
from .exam import load_presets, make_plan
from .llm import OllamaLLM
from .mistakes import MistakeLog, pick_focus
from .prompts import PromptStore
from .session import Deps, Session
from .stt import make_stt
from .thermal import ThermalGuard
from .tts import make_tts

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("kerstin")

deps: Deps | None = None


async def _focus_for_start(deps: Deps, use_focus: object) -> list[str]:
    """Resolve focus keys for a start frame; strict bool and fail-safe."""
    if use_focus is not True or deps.mistakes is None:
        return []
    try:
        summary = await deps.mistakes.summary(days=30)
        focus = pick_focus(summary, set(deps.prompts.focus_instructions()))
    except Exception as exc:  # noqa: BLE001 — steering is optional
        log.warning("focus lookup failed (%s)", type(exc).__name__)
        return []
    log.info("focus=%s", ",".join(focus))
    return focus


@asynccontextmanager
async def lifespan(app: FastAPI):
    global deps
    deps = Deps(
        stt=make_stt(settings),
        llm=OllamaLLM(settings),
        tts=make_tts(settings),
        prompts=PromptStore(settings.prompts_dir),
        history_max_turns=settings.history_max_turns,
        llm_warmup=settings.llm_warmup,
        first_clause_min_words=settings.tts_first_clause_min_words,
        stt_min_rms_dbfs=settings.stt_min_rms_dbfs,
        stt_filter=settings.stt_filter,
        feedback_lang=settings.feedback_lang,
        ollama_model=settings.ollama_model,
        feedback_model=settings.feedback_model,
        feedback_temperature=settings.feedback_temperature,
        ollama_max_loaded=settings.ollama_max_loaded,
        hint_temperature=settings.hint_temperature,
        mistakes=(
            MistakeLog(settings.mistake_log_path, settings.mistake_log_max_days)
            if settings.mistake_log_enabled
            else None
        ),
        thermal=(
            ThermalGuard(settings.thermal_hot_c, settings.thermal_resume_c)
            if settings.thermal_guard
            else None
        ),
    )
    log.info(
        "Kerstin %s ready: model=%s stt=%s tts=%s",
        __version__, settings.ollama_model, settings.stt_backend, settings.tts_backend,
    )
    yield


app = FastAPI(title="Kerstin", version=__version__, lifespan=lifespan)


@app.get("/health")
async def health() -> JSONResponse:
    assert deps is not None
    if deps.thermal is None:
        thermal_state = "disabled"
        gpu_temp_c = None
    else:
        thermal = await deps.thermal.check()
        thermal_state = thermal.state
        gpu_temp_c = thermal.temp_c
    return JSONResponse(
        {
            "version": __version__,
            "ollama": await deps.llm.health(),
            "model": settings.ollama_model,
            "stt_backend": settings.stt_backend,
            "tts_backend": settings.tts_backend,
            "gpu_temp_c": gpu_temp_c,
            "thermal": thermal_state,
        }
    )


@app.get("/api/scenarios")
async def scenarios() -> JSONResponse:
    assert deps is not None
    return JSONResponse(
        [{"key": s.key, "title": s.title} for s in deps.prompts.scenarios().values()]
    )


@app.get("/api/mistakes")
async def mistakes_summary() -> JSONResponse:
    assert deps is not None
    if deps.mistakes is None:
        return JSONResponse({"enabled": False, "sessions": 0, "categories": []})
    summary = await deps.mistakes.summary()
    return JSONResponse({"enabled": True, **summary})


@app.delete("/api/mistakes")
async def clear_mistakes() -> JSONResponse:
    assert deps is not None
    if deps.mistakes is None:
        raise HTTPException(status_code=404, detail="mistake log disabled")
    await deps.mistakes.clear()
    return JSONResponse({"cleared": True})


@app.get("/kerstin-ca.crt")
async def ca_cert() -> Response:
    """Serve the public local CA so clients can trust it (never a private key)."""
    path = settings.tls_ca_certfile
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="CA certificate not available")
    data = path.read_bytes()
    if b"PRIVATE KEY" in data:
        log.error("Refusing to serve %s: it contains a private key", path)
        raise HTTPException(status_code=500, detail="CA file contains a private key")
    return Response(content=data, media_type="application/x-x509-ca-cert")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    """Protocol: see docs/PROTOCOL.md."""
    assert deps is not None
    await ws.accept()
    session: Session | None = None

    async def send_json(obj: dict) -> None:
        await ws.send_text(json.dumps(obj, ensure_ascii=False))

    async def send_bytes(b: bytes) -> None:
        await ws.send_bytes(b)

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                if session is None:
                    await send_json({"type": "error", "message": "send 'start' first"})
                    continue
                await session.handle_audio(msg["bytes"])
                continue

            data = json.loads(msg.get("text") or "{}")
            kind = data.get("type")
            if kind == "start":
                if session:
                    await session.close()
                exam_key = data.get("exam")
                plan = None
                if exam_key is not None:
                    if not isinstance(exam_key, str):
                        session = None
                        await send_json(
                            {"type": "error", "message": "exam must be a preset key"}
                        )
                        continue
                    try:
                        catalog = load_presets(settings.prompts_dir)
                        seed = data.get("exam_seed")
                        if not isinstance(seed, int) or isinstance(seed, bool):
                            seed = random.randrange(0, 2**31)
                        plan = make_plan(exam_key, catalog, seed)
                    except ValueError as exc:
                        session = None
                        await send_json({"type": "error", "message": str(exc)})
                        continue
                    focus = []
                else:
                    focus = await _focus_for_start(deps, data.get("use_focus"))
                session = Session(
                    deps=deps,
                    send_json=send_json,
                    send_bytes=send_bytes,
                    scenario_key=data.get("scenario") or settings.default_scenario,
                    focus=focus,
                    exam=plan,
                )
                await session.start()
            elif kind == "interrupt" and session:
                await session.interrupt()
            elif kind == "exam_next":
                if session and session.exam is not None:
                    await session.exam_next()
                else:
                    await send_json(
                        {"type": "error", "message": "exam_next outside exam mode"}
                    )
            elif kind == "hint":
                if session:
                    await session.hint(str(data.get("query") or ""))
                else:
                    await send_json({"type": "error", "message": "send 'start' first"})
            elif kind == "end" and session:
                await session.feedback(
                    data.get("feedback_lang"),
                    save_mistakes=data.get("save_mistakes") is True,
                )
            elif kind == "ping":
                await send_json({"type": "pong"})
            else:
                await send_json({"type": "error", "message": f"unknown message {kind!r}"})
    except WebSocketDisconnect:
        pass
    finally:
        if session:
            await session.close()


# Static frontend (mounted last so /ws, /health, /api win)
@app.get("/")
async def index() -> FileResponse:
    return FileResponse(settings.frontend_dir / "index.html")


app.mount("/", StaticFiles(directory=settings.frontend_dir), name="frontend")
