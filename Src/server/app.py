"""
FastAPI application for AnkleFlex.

Serves the web UI and provides:
  GET  /          → index.html
  GET  /stream    → Server-Sent Events (state at 20 Hz)
  POST /tare      → Reset session min/max; recalibrate offset on hardware
  GET  /status    → One-shot JSON state snapshot
  POST /emulation/weight → Set simulated weight (emulation mode only)
"""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

# ── Constants ────────────────────────────────────────────────────────────────
HISTORY_LENGTH = 60
THRESHOLD_UP   = 500
THRESHOLD_DOWN = -500

# ── Shared state (written by sensor loop, read by SSE clients) ────────────────
_state: dict = {
    "weight": 0.0,
    "min_weight": 0.0,
    "max_weight": 0.0,
    "emulation": False,
    "history": [],       # list of {"t": "HH:MM:SS", "w": float}, capped at HISTORY_LENGTH
    "above_count": 0,    # readings that exceeded THRESHOLD_UP since last tare
    "below_count": 0,    # readings that fell below THRESHOLD_DOWN since last tare
}

_loadcell = None
_emulate: bool = False
_STATIC = Path(__file__).parent / "static"


# ── Public API for main.py ────────────────────────────────────────────────────

def configure(loadcell, emulate: bool) -> None:
    """Wire up the loadcell and emulation flag before starting uvicorn."""
    global _loadcell, _emulate
    _loadcell = loadcell
    _emulate = emulate
    _state["emulation"] = emulate


def do_tare() -> None:
    """Reset session min/max, current weight, and history in shared state.
    Thread-safe (GIL protects dict writes).
    The caller is responsible for first invoking loadcell.tare() to
    recalibrate the hardware/emulation zero reference.
    """
    _state["weight"] = 0.0
    _state["min_weight"] = 0.0
    _state["max_weight"] = 0.0
    _state["history"] = []
    _state["above_count"] = 0
    _state["below_count"] = 0


# ── Background sensor reader ──────────────────────────────────────────────────

_SENSOR_HZ = 20          # target sensor poll rate
_SENSOR_INTERVAL = 1 / _SENSOR_HZ

async def _sensor_loop() -> None:
    """Reads the load cell at 20 Hz and updates shared state."""
    loop = asyncio.get_running_loop()
    while True:
        try:
            raw = await loop.run_in_executor(None, _loadcell.get_weight)
            if raw is not None and raw is not False and raw != -1:
                w = float(raw)
                _state["weight"] = w
                if w > _state["max_weight"]:
                    _state["max_weight"] = w
                if w < _state["min_weight"]:
                    _state["min_weight"] = w
                # Rolling history buffer
                _state["history"].append({"t": datetime.now().strftime("%H:%M:%S"), "w": w})
                if len(_state["history"]) > HISTORY_LENGTH:
                    _state["history"] = _state["history"][-HISTORY_LENGTH:]
                # Threshold exceedance counters
                if w > THRESHOLD_UP:
                    _state["above_count"] += 1
                elif w < THRESHOLD_DOWN:
                    _state["below_count"] += 1
        except Exception as exc:
            # Log but never crash — sensor errors are recoverable
            print(f"[sensor] read error: {exc}")
        await asyncio.sleep(_SENSOR_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_sensor_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(lifespan=lifespan, title="AnkleFlex")
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(_STATIC / "index.html")


@app.get("/stream", summary="Server-Sent Events — pushes state at 20 Hz")
async def stream(request: Request):
    async def generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                yield {"data": json.dumps(_state)}
                await asyncio.sleep(_SENSOR_INTERVAL)
        finally:
            pass  # cleanup on disconnect

    return EventSourceResponse(generator())


@app.post("/tare", summary="Reset session min/max and recalibrate offset")
async def tare():
    # Run the (potentially blocking) hardware tare in a thread executor so we
    # don't stall the async event loop.  For emulation this returns instantly.
    if _loadcell is not None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _loadcell.tare)
    do_tare()
    return {"ok": True}


@app.get("/status", summary="One-shot state snapshot (no streaming)")
async def status():
    return JSONResponse(_state)


@app.post("/emulation/weight", summary="Set simulated weight (emulation mode only)")
async def set_emulated_weight(request: Request):
    if not _emulate:
        return JSONResponse({"error": "not in emulation mode"}, status_code=403)
    body = await request.json()
    weight = float(body.get("weight", 0.0))
    if hasattr(_loadcell, "set_weight"):
        _loadcell.set_weight(weight)
    return {"ok": True}
