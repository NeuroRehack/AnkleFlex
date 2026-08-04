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
import sys
import threading
import time
import traceback
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
# Time budget for a recover() power-cycle before we treat the hw executor as
# blocked (a bounded reset can take a few seconds when the chip is unresponsive).
_RECOVER_TIMEOUT = 12.0
# A single read taking longer than this is logged (helps spot creeping latency
# before it becomes a full timeout).
_SLOW_READ_WARN_S = 0.5
# How often to emit a one-line heartbeat summarising sensor health.
_HEARTBEAT_SEC = 5.0
# If no valid read arrives for this long, dump all thread stacks once so we can
# see exactly where things are stuck.
_WATCHDOG_SEC = 10.0

# Dedicated single-worker executor for all load-cell hardware access.  Keeping
# the (bit-banged, potentially slow) HX711 reads off the default thread pool
# means a slow/stuck read can never starve the request handlers (/stream,
# /tare, /status), and it guarantees the chip is only ever driven from one
# thread at a time.
_hw_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hx711")


def _dump_thread_stacks(reason: str) -> None:
    """Log the current stack of every live thread.

    Invaluable for the field drop-out: it shows whether a hardware read/reset
    is parked inside the hx711 driver (chip issue) or whether the executor
    itself is starved (software wedge).
    """
    lines = [f"[watchdog] thread stack dump ({reason}):"]
    frames = sys._current_frames()
    for thread in threading.enumerate():
        frame = frames.get(thread.ident)
        lines.append(f"  Thread {thread.name!r} (id={thread.ident}, daemon={thread.daemon})")
        if frame is None:
            lines.append("    <no frame available>")
            continue
        for filename, lineno, func, text in traceback.extract_stack(frame):
            lines.append(f"    {filename}:{lineno} in {func}")
            if text:
                lines.append(f"        {text.strip()}")
    logger.warning("\n".join(lines))


async def _recover_hx711(loop: asyncio.AbstractEventLoop) -> bool:
    """Attempt to wake the HX711 with a bounded power-cycle. Returns success.

    Driving SCK LOW (which reset() does during power-up) releases the chip
    from power-down and allows DOUT to go LOW again.  We time the whole thing
    and, if it does not even complete, dump thread stacks so we can tell a
    stuck chip from a starved executor.
    """
    if _loadcell is None or not hasattr(_loadcell, "recover"):
        return False
    _state["sensor_ok"] = False
    t0 = time.monotonic()
    logger.warning("[sensor] attempting HX711 recover()/power-cycle...")
    try:
        ok = bool(
            await asyncio.wait_for(
                loop.run_in_executor(_hw_executor, _loadcell.recover),
                timeout=_RECOVER_TIMEOUT,
            )
        )
    except asyncio.TimeoutError:
        logger.error(
            "[sensor] recover() did not finish within %.1fs - hw executor may be "
            "blocked by a stuck read; dumping stacks",
            _RECOVER_TIMEOUT,
        )
        _dump_thread_stacks("recover-timeout")
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error("[sensor] recover() error: %s", exc)
        return False
    dur = time.monotonic() - t0
    if ok:
        logger.info("[sensor] recover() succeeded in %.3fs - resuming reads", dur)
    else:
        logger.warning(
            "[sensor] recover() ran in %.3fs but chip still unresponsive "
            "(power-cycle did not wake it) - diag=%s",
            dur,
            _loadcell.get_diagnostics() if hasattr(_loadcell, "get_diagnostics") else {},
        )
    return ok


async def _sensor_loop() -> None:
    """Read the load cell at 20 Hz and update shared state."""
    loop = asyncio.get_running_loop()
    prev_w = None
    lower_up_pending = False
    consecutive_timeouts = 0
    consecutive_bad = 0

    # Diagnostics accumulators.
    stats = {"ok": 0, "bad": 0, "timeout": 0, "errors": 0, "recover_ok": 0, "recover_fail": 0}
    win = {"reads": 0, "lat_sum": 0.0, "lat_max": 0.0}
    last_good = time.monotonic()
    last_heartbeat = time.monotonic()
    stale_since: float | None = None
    watchdog_dumped = False

    def _diag() -> dict:
        if _loadcell is not None and hasattr(_loadcell, "get_diagnostics"):
            return _loadcell.get_diagnostics()
        return {}

    while True:
        t0 = time.monotonic()
        try:
            raw = await asyncio.wait_for(
                loop.run_in_executor(_hw_executor, _loadcell.get_weight),
                timeout=_SENSOR_READ_TIMEOUT,
            )
            lat = time.monotonic() - t0
            win["reads"] += 1
            win["lat_sum"] += lat
            win["lat_max"] = max(win["lat_max"], lat)
            if lat > _SLOW_READ_WARN_S:
                logger.warning("[sensor] slow read: %.3fs (near %.1fs timeout)", lat, _SENSOR_READ_TIMEOUT)
            consecutive_timeouts = 0
            if raw is not None and raw is not False and raw != -1:
                stats["ok"] += 1
                if not _state["sensor_ok"]:
                    down = time.monotonic() - (stale_since or last_good)
                    logger.info("[sensor] sensor RECOVERED after %.1fs stale (value=%.2f kg)", down, float(raw))
                consecutive_bad = 0
                stale_since = None
                watchdog_dumped = False
                last_good = time.monotonic()
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
                stats["bad"] += 1
                consecutive_bad += 1
                if _state["sensor_ok"]:
                    stale_since = time.monotonic()
                    logger.warning(
                        "[sensor] sensor STALE - bad read; holding last %.2f kg "
                        "(last good %.1fs ago), diag=%s",
                        _state["weight"],
                        time.monotonic() - last_good,
                        _diag(),
                    )
                _state["sensor_ok"] = False
                if consecutive_bad >= _BAD_READS_BEFORE_RESET:
                    logger.warning(
                        "[sensor] %d consecutive bad reads - attempting HX711 recovery",
                        consecutive_bad,
                    )
                    ok = await _recover_hx711(loop)
                    stats["recover_ok" if ok else "recover_fail"] += 1
                    consecutive_bad = 0
        except asyncio.TimeoutError:
            stats["timeout"] += 1
            consecutive_timeouts += 1
            if _state["sensor_ok"]:
                stale_since = time.monotonic()
            _state["sensor_ok"] = False
            logger.warning(
                "[sensor] get_weight() TIMED OUT after %.2fs (%d consecutive) - "
                "read stuck in driver or executor starved; diag=%s",
                time.monotonic() - t0,
                consecutive_timeouts,
                _diag(),
            )
            if consecutive_timeouts >= _TIMEOUTS_BEFORE_RESET:
                ok = await _recover_hx711(loop)
                stats["recover_ok" if ok else "recover_fail"] += 1
                consecutive_timeouts = 0
        except Exception as exc:  # noqa: BLE001
            stats["errors"] += 1
            logger.error("[sensor] read error: %s", exc, exc_info=True)

        # ── Watchdog: dump stacks once if we've had no valid read for a while ──
        now = time.monotonic()
        if now - last_good > _WATCHDOG_SEC and not watchdog_dumped:
            logger.error(
                "[sensor] NO valid read for %.1fs - dumping thread stacks + diagnostics",
                now - last_good,
            )
            _dump_thread_stacks("no-good-read")
            logger.error("[sensor] hardware diagnostics: %s", _diag())
            watchdog_dumped = True

        # ── Heartbeat: periodic one-line health summary ───────────────────────
        if now - last_heartbeat >= _HEARTBEAT_SEC:
            elapsed = now - last_heartbeat
            reads = win["reads"]
            avg_ms = (win["lat_sum"] / reads * 1000) if reads else 0.0
            logger.info(
                "[hb] ok=%d bad=%d timeout=%d err=%d recover(ok=%d fail=%d) | "
                "sensor_ok=%s last_good=%.1fs ago | reads/s=%.1f avg=%.1fms max=%.1fms | diag=%s",
                stats["ok"],
                stats["bad"],
                stats["timeout"],
                stats["errors"],
                stats["recover_ok"],
                stats["recover_fail"],
                _state["sensor_ok"],
                now - last_good,
                reads / elapsed if elapsed else 0.0,
                avg_ms,
                win["lat_max"] * 1000,
                _diag(),
            )
            win = {"reads": 0, "lat_sum": 0.0, "lat_max": 0.0}
            last_heartbeat = now

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
