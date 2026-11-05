"""FastAPI app: serves the browser client and the /ws conversation endpoint.

Run:  cd backend && uvicorn kerstin.main:app --host 127.0.0.1 --port 8770
(or `make run` from the project root)
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import settings
from .llm import OllamaLLM
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
                session = Session(
                    deps=deps,
                    send_json=send_json,
                    send_bytes=send_bytes,
                    scenario_key=data.get("scenario") or settings.default_scenario,
                )
                await session.start()
            elif kind == "interrupt" and session:
                await session.interrupt()
            elif kind == "end" and session:
                await session.feedback(data.get("feedback_lang"))
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
