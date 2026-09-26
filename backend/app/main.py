from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from .config import load_config
from .engine import InspectionEngine, InvalidTransition


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    engine = InspectionEngine(config)
    engine.start_background()
    app.state.engine = engine
    try:
        yield
    finally:
        engine.shutdown()


app = FastAPI(title="Printing Inspection Demo", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_engine(request: Request) -> InspectionEngine:
    return request.app.state.engine


@app.get("/health")
def health(request: Request) -> dict[str, object]:
    engine = get_engine(request)
    if not engine.ready:
        raise HTTPException(status_code=503, detail="Inspection engine is starting")
    return {"status": "ok", "engine_ready": True, "version": app.version}


@app.get("/api/status")
def status(request: Request) -> dict[str, object]:
    return get_engine(request).status_snapshot()


@app.get("/api/live/frame.jpg")
def live_frame(request: Request) -> Response:
    frame = get_engine(request).frame_bytes()
    if frame is None:
        raise HTTPException(status_code=503, detail="Live frame is not ready")
    return Response(
        content=frame,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/api/rolls")
def rolls(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    return get_engine(request).database.list_rolls(limit, offset)


@app.get("/api/defects")
def defects(
    request: Request,
    roll_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    return get_engine(request).database.list_defects(roll_id, limit, offset)


@app.get("/api/defects/{defect_id}")
def defect_detail(defect_id: str, request: Request) -> dict[str, object]:
    item = get_engine(request).database.get_defect(defect_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Defect not found")
    return item


@app.get("/api/defects/{defect_id}/thumbnail.jpg")
def defect_thumbnail(defect_id: str, request: Request) -> FileResponse:
    engine = get_engine(request)
    relative_path = engine.database.defect_image_path(defect_id)
    if not relative_path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    path = (engine.config.storage_path / relative_path).resolve()
    storage_root = engine.config.storage_path.resolve()
    if storage_root not in path.parents or not path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(Path(path), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})


def run_command(request: Request, command: str) -> dict[str, object]:
    engine = get_engine(request)
    try:
        return getattr(engine, f"command_{command}")()
    except InvalidTransition as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/demo/start")
def demo_start(request: Request) -> dict[str, object]:
    return run_command(request, "start")


@app.post("/api/demo/stop")
def demo_stop(request: Request) -> dict[str, object]:
    return run_command(request, "stop")


@app.post("/api/demo/reset")
def demo_reset(request: Request) -> dict[str, object]:
    return run_command(request, "reset")


@app.websocket("/ws/inspection")
async def inspection_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    engine: InspectionEngine = websocket.app.state.engine
    snapshot = engine.snapshot_envelope()
    cursor = snapshot["sequence"]
    await websocket.send_json(snapshot)
    try:
        while True:
            events = engine.events_after(cursor)
            for event in events:
                await websocket.send_json(event)
                cursor = max(cursor, event["sequence"])
            await websocket.send_json(engine.telemetry_envelope())
            await asyncio.sleep(1.0 / engine.config.telemetry.hz)
    except (WebSocketDisconnect, RuntimeError):
        return

