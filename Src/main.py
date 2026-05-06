"""Main entry point for the AnkleFlex server application."""

import logging
import os
import threading

import uvicorn

import led
from hardware.loadcell import CALIBRATION_FACTOR, LoadCell
from logging_config import setup_logging
from server.app import app, configure, do_tare


# ── Mode selection ─────────────────────────────────────────────────────────────
setup_logging()
logger = logging.getLogger("ankleflex.main")

# Use automatic emulation detection from LoadCell
_hx711 = None  # Let LoadCell handle emulation/hardware selection


# ── Entry point ────────────────────────────────────────────────────────────────
def main() -> None:
    """Run the AnkleFlex server."""
    led.init_led()
    led.turn_on_led()


    loadcell = LoadCell(hx711=_hx711)
    loadcell.initialize()
    emulation_mode = getattr(loadcell, 'emulation', False)
    configure(loadcell, emulate=emulation_mode)

    if not emulation_mode:
        from hardware.button import Button

        btn = Button(loadcell, on_tare=do_tare)
        btn_thread = threading.Thread(target=btn.run, daemon=True)
        btn_thread.start()

    logger.info(f"emulation={'ON' if emulation_mode else 'OFF'}")
    logger.info("Starting server → http://0.0.0.0:8000/")
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
    finally:
        led.turn_off_led()
        if hasattr(loadcell, "cleanup"):
            loadcell.cleanup()


if __name__ == "__main__":
    main()
