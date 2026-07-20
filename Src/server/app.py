"""FastAPI application for AnkleFlex.

Serves the web UI and provides:
  GET  /          → index.html
  GET  /stream    → Server-Sent Events (state at 20 Hz)
    POST /tare      → Reset session min/max
  GET  /status    → One-shot JSON state snapshot
  POST /emulation/weight → Set simulated weight (emulation mode only)
"""

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse


# Input validation models
class WeightPayload(BaseModel):
    weight: float = 0.0


class ThresholdPayload(BaseModel):
    upper: float
    lower: float


logger = logging.getLogger("ankleflex.server.app")

# ── Constants ────────────────────────────────────────────────────────────────
_SENSOR_HZ = 20  # target sensor poll rate
_MAX_XRANGE_SEC = 20 * 60  # 20 min window
HISTORY_LENGTH = (
    _SENSOR_HZ * _MAX_XRANGE_SEC
)  # enough buffer for UI slider (24,000 for 20min at 20Hz)

# ── Shared state (written by sensor loop, read by SSE clients) ────────────────
_state: dict = {
    "weight": 0.0,
    "min_weight": 0.0,
    "max_weight": 0.0,
    "emulation": False,
    "sensor_ok": True,  # False when the load cell is failing reads / recovering
    "history": [],  # list of {"t": "HH:MM:SS", "w": float}, capped at HISTORY_LENGTH
    "lower_up": 0,  # below lower threshold to above lower threshold
    "lower_down": 0,  # above lower threshold to below lower threshold
    "upper_up": 0,  # below upper threshold to above upper threshold
    "upper_down": 0,  # above upper threshold to below upper threshold
    "sequence_count": 0,  # lower up followed by upper up
    "threshold_up": 30,  # default, will be set by UI
    "threshold_down": -30,  # default, will be set by UI
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
    reset the hardware/emulation session state.
    """
    _state["weight"] = 0.0
    _state["min_weight"] = 0.0
    _state["max_weight"] = 0.0
    _state["history"] = []
    _state["lower_up"] = 0
    _state["lower_down"] = 0
    _state["upper_up"] = 0
    _state["upper_down"] = 0
    _state["sequence_count"] = 0
    logger.info("do_tare called")


# ── Background sensor reader ──────────────────────────────────────────────────

_SENSOR_INTERVAL = 1 / _SENSOR_HZ
# Maximum time to wait for a single get_weight() call before treating the
# HX711 as stuck and timing out.
_SENSOR_READ_TIMEOUT = 2.0
# How many consecutive timeouts before attempting an HX711 reset.
_TIMEOUTS_BEFORE_RESET = 3
# How many consecutive bad reads (get_weight() -> None) before attempting an
# HX711 power-cycle. At 20 Hz, 20 reads is ~1 s of no valid data.
_BAD_READS_BEFORE_RESET = 20

# Dedicated single-worker executor for all load-cell hardware access.  Keeping
# the (bit-banged, potentially slow) HX711 reads off the default thread pool
# means a slow/stuck read can never starve the request handlers (/stream,
# /tare, /status), and it guarantees the chip is only ever driven from one
# thread at a time.
_hw_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hx711")


async def _recover_hx711(loop: asyncio.AbstractEventLoop) -> None:
    """Attempt to wake the HX711 from power-down by issuing a reset.

    Driving SCK LOW (which reset() does during power-up) releases the chip
    from power-down and allows DOUT to go LOW again, which unblocks any
    thread currently stuck in hx711._read().
    """
    if _loadcell is None or not hasattr(_loadcell, "recover"):
        return
    _state["sensor_ok"] = False
    logger.warning("[sensor] Attempting HX711 recover() to recover from power-down...")
    try:
        await asyncio.wait_for(loop.run_in_executor(_hw_executor, _loadcell.recover), timeout=8.0)
        logger.info("[sensor] HX711 recover() completed - resuming reads")
    except asyncio.TimeoutError:
        logger.error("[sensor] HX711 recover() also timed out - hardware may be disconnected")
    except Exception as exc:
        logger.error("[sensor] HX711 recover() error: %s", exc)


async def _sensor_loop() -> None:
    """Read the load cell at 20 Hz and update shared state."""
    loop = asyncio.get_running_loop()
    prev_w = None
    lower_up_pending = False
    consecutive_timeouts = 0
    consecutive_bad = 0
    while True:
        try:
            raw = await asyncio.wait_for(
                loop.run_in_executor(_hw_executor, _loadcell.get_weight),
                timeout=_SENSOR_READ_TIMEOUT,
            )
            consecutive_timeouts = 0
            if raw is not None and raw is not False and raw != -1:
                consecutive_bad = 0
                _state["sensor_ok"] = True
                w = float(raw)
                _state["weight"] = w
                if w > _state["max_weight"]:
                    _state["max_weight"] = w
                if w < _state["min_weight"]:
                    _state["min_weight"] = w
                # Rolling history buffer (include ms-since-epoch timestamp for robust frontend filtering)
                now = datetime.now()
                _state["history"].append(
                    {
                        "t": now.strftime("%H:%M:%S"),
                        "ts": int(now.timestamp() * 1000),  # ms since epoch
                        "w": w,
                    }
                )
                if len(_state["history"]) > HISTORY_LENGTH:
                    _state["history"] = _state["history"][-HISTORY_LENGTH:]

                # Use dynamic thresholds from state
                threshold_up = _state.get("threshold_up", 30)
                threshold_down = _state.get("threshold_down", -30)

                if prev_w is not None:
                    # Lower threshold crossings
                    if prev_w >= threshold_down and w < threshold_down:
                        _state["lower_down"] += 1
                        lower_up_pending = False
                    elif prev_w < threshold_down and w >= threshold_down:
                        _state["lower_up"] += 1
                        lower_up_pending = True
                    # Upper threshold crossings
                    if prev_w <= threshold_up and w > threshold_up:
                        _state["upper_up"] += 1
                        if lower_up_pending:
                            _state["sequence_count"] += 1
                            lower_up_pending = False
                    elif prev_w > threshold_up and w <= threshold_up:
                        _state["upper_down"] += 1
                prev_w = w
            else:
                # Bad read (get_weight() returned None): hold the last value,
                # mark the sensor stale, and power-cycle after enough failures.
                consecutive_bad += 1
                _state["sensor_ok"] = False
                if consecutive_bad >= _BAD_READS_BEFORE_RESET:
                    logger.warning(
                        "[sensor] %d consecutive bad reads — attempting HX711 recovery",
                        consecutive_bad,
                    )
                    await _recover_hx711(loop)
                    consecutive_bad = 0
        except asyncio.TimeoutError:
            consecutive_timeouts += 1
            _state["sensor_ok"] = False
            logger.warning(
                "[sensor] get_weight() timed out (%d consecutive) — HX711 may be in power-down",
                consecutive_timeouts,
            )
            if consecutive_timeouts >= _TIMEOUTS_BEFORE_RESET:
                await _recover_hx711(loop)
                consecutive_timeouts = 0
        except Exception as exc:
            logger.error(f"[sensor] read error: {exc}")
        await asyncio.sleep(_SENSOR_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager to run the sensor loop."""
    task = asyncio.create_task(_sensor_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    _hw_executor.shutdown(wait=False)


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(lifespan=lifespan, title="AnkleFlex")
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/", include_in_schema=False)
async def index():
    """Serve the main index.html page."""
    return FileResponse(_STATIC / "index.html")


# New: /history endpoint for full history
@app.get("/history", summary="Get full weight history (one-shot)")
async def get_history():
    """Return the full history buffer as a one-shot JSON response."""
    return JSONResponse({"history": _state["history"]})


@app.get("/stream", summary="Server-Sent Events — pushes state at 20 Hz")
async def stream(request: Request):
    """Stream state updates to the client at 20 Hz using SSE (no history)."""

    async def generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                # Send all state except history
                state_copy = dict(_state)
                state_copy.pop("history", None)
                yield {"data": json.dumps(state_copy)}
                await asyncio.sleep(_SENSOR_INTERVAL)
        finally:
            pass  # cleanup on disconnect

    return EventSourceResponse(generator())


@app.post("/tare", summary="Reset session min/max")
async def tare():
    """Reset session min/max for the load cell."""
    # Run the (potentially blocking) hardware tare in a thread executor so we
    # don't stall the async event loop.  For emulation this returns instantly.
    if _loadcell is not None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(_hw_executor, _loadcell.tare)
    do_tare()
    return {"ok": True}


@app.get("/status", summary="One-shot state snapshot (no streaming)")
async def status():
    """Return a one-shot snapshot of the current state."""
    return JSONResponse(_state)


@app.post("/emulation/weight", summary="Set simulated weight (emulation mode only)")
async def set_emulated_weight(payload: WeightPayload):
    """Set the simulated weight value (emulation mode only)."""
    if not _emulate:
        return JSONResponse({"error": "not in emulation mode"}, status_code=403)
    if hasattr(_loadcell, "set_weight"):
        _loadcell.set_weight(payload.weight)
    return {"ok": True}


@app.post("/thresholds", summary="Update threshold values")
async def update_thresholds(payload: ThresholdPayload):
    """Update threshold values from the UI."""
    _state["threshold_up"] = payload.upper
    _state["threshold_down"] = payload.lower
    return {
        "ok": True,
        "threshold_up": _state["threshold_up"],
        "threshold_down": _state["threshold_down"],
    }
