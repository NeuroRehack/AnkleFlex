"""Physical button handler for AnkleFlex (Raspberry Pi only).

Button behaviour:
    - Long press (> 1 s between releases): tare / reset
    - Quick second press (< 1 s after first release): reboot Pi

Run Button.run() in a daemon thread.
"""

import logging
import os
import threading
import time
from collections.abc import Callable

logger = logging.getLogger("ankleflex.button")

BUTTON_PIN = 17  # GPIO 17 / Board pin 11


class Button:
    """Button handler for AnkleFlex physical button."""

    def __init__(self, loadcell, on_tare: Callable | None = None):
        """Initialize the Button handler.

        Args:
            loadcell: LoadCell instance (used to recalibrate offset on tare).
            on_tare:  Optional callback invoked after a tare operation completes.
                      Called from the button thread — must be thread-safe.
        """
        try:
            import RPi.GPIO as GPIO
            EMULATION = False
        except (ImportError, ModuleNotFoundError):
            EMULATION = True
            # Minimal mock GPIO for emulation
            class MockGPIO:
                BCM = None
                IN = None
                PUD_UP = None
                BOTH = None
                def setmode(self, *a, **kw): pass
                def setup(self, *a, **kw): pass
                def add_event_detect(self, *a, **kw): pass
                def cleanup(self): pass
            GPIO = MockGPIO()
            logger.info("[EMULATION] Button using mock GPIO")

        import led  # led.py is on sys.path via Src/

        self._GPIO = GPIO
        self._led = led
        self.loadcell = loadcell
        self.on_tare = on_tare

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(BUTTON_PIN, GPIO.BOTH, callback=self._callback, bouncetime=100)

        self._last_press = time.time()
        self._mode = -1
        self._last_mode = -1
        self._last_mode_change = time.time()

    def run(self) -> None:
        """Blocking loop — call from a daemon thread."""
        while True:
            if self._mode != self._last_mode:
                self._last_mode = self._mode
                if self._mode == 0:
                    self._do_tare()
                elif self._mode == 1:
                    self._do_reboot()
            time.sleep(min(1.0, time.time() - self._last_mode_change))

    def _do_tare(self) -> None:
        logger.info("Tare triggered")
        blink = threading.Thread(target=self._led.blink_led, daemon=True)
        blink.start()
        self.loadcell.tare()
        if self.on_tare:
            self.on_tare()
        blink.join()

    def _do_reboot(self) -> None:
        logger.warning("Reboot triggered")
        self._led.turn_off_led()
        os.system("sudo reboot")

    def _callback(self, channel) -> None:
        dt = time.time() - self._last_press
        if dt > 1.0:
            self._mode = 0
            self._last_mode = -1
            self._last_mode_change = time.time()
        elif dt >= 0.1:
            self._mode = 1
            self._last_mode_change = time.time()
        self._last_press = time.time()

    def cleanup(self) -> None:
        """Clean up GPIO resources for the button."""
        self._GPIO.cleanup()
