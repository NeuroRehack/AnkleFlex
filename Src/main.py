"""Main entry point for the AnkleFlex server application."""

import logging
import os
import threading

import uvicorn

import led
from hardware.loadcell import CALIBRATION_FACTOR, LoadCell
from logging_config import setup_logging
from server.app import app, configure, do_tare

"""AnkleFlex — entry point.

Selects hardware or emulation mode based on the environment variable
ANKLEFLEX_EMULATE_LOADCELL, then starts the FastAPI/Uvicorn server.

Usage:
    # Emulation mode (development, no hardware required)
    ANKLEFLEX_EMULATE_LOADCELL=1 python Src/main.py

    # Hardware mode (Raspberry Pi with load cell connected)
    python Src/main.py
"""

# ── Mode selection ─────────────────────────────────────────────────────────────
EMULATE = os.environ.get("ANKLEFLEX_EMULATE_LOADCELL", "0") == "1"
setup_logging()
logger = logging.getLogger("ankleflex.main")
logger.info(f"emulation={'ON' if EMULATE else 'OFF'}")

# LoadCell and CALIBRATION_FACTOR can always be imported — hardware GPIO imports
# are deferred inside LoadCell.__init__, so this is safe on non-Pi systems.

if EMULATE:
    from emulation.hx711 import EmulatedHX711

    _hx711 = EmulatedHX711(calibration_factor=CALIBRATION_FACTOR)
else:
    _hx711 = None  # LoadCell.__init__ will open real hardware


# ── Entry point ────────────────────────────────────────────────────────────────
def main() -> None:
    """Run the AnkleFlex server."""
    led.init_led()
    led.turn_on_led()

    loadcell = LoadCell(hx711=_hx711)
    loadcell.initialize()
    configure(loadcell, emulate=EMULATE)

    if not EMULATE:
        from hardware.button import Button

        btn = Button(loadcell, on_tare=do_tare)
        btn_thread = threading.Thread(target=btn.run, daemon=True)
        btn_thread.start()

    logger.info("Starting server → http://0.0.0.0:8000/")
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
    finally:
        led.turn_off_led()
        if hasattr(loadcell, "cleanup"):
            loadcell.cleanup()


if __name__ == "__main__":
    main()
