"""Real LoadCell implementation using HX711 ADC.

Only works on Raspberry Pi with the load cell hardware connected.
"""

import logging
import queue
import threading

logger = logging.getLogger("ankleflex.loadcell")

LOADCELL_DOUT_PIN = 2  # GPIO 2 / Board pin 3
LOADCELL_SCK_PIN = 3  # GPIO 3 / Board pin 5
CALIBRATION_FACTOR = -1554  # Obtained from calibration script


def _run_with_timeout(func, timeout: float):
    """Run a no-argument callable in a thread with a timeout.

    Returns -1 if the timeout is exceeded, otherwise the function's result.
    """
    q: queue.Queue = queue.Queue()

    def wrapper():
        q.put(func())

    t = threading.Thread(target=wrapper, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return -1
    return q.get()


class LoadCell:
    """Reads force from a TAL220B load cell via HX711 ADC.

    An optional ``hx711`` argument may be passed to inject an emulated HX711
    (e.g. EmulatedHX711) instead of opening the real hardware.  All other
    logic — offset arithmetic, tare, calibration — runs unchanged either way.
    """

    def __init__(self, hx711=None) -> None:
        """Initialize the LoadCell object."""
        if hx711 is not None:
            # Emulation path: caller supplies a pre-built HX711 stub.
            self.hx711 = hx711
            self._GPIO = None
            self.emulation = True
        else:
            try:
                import RPi.GPIO as GPIO
                from hx711 import HX711
                self._GPIO = GPIO
                logger.info("Initializing HX711 (hardware mode)...")
                self.hx711 = HX711(
                    dout_pin=LOADCELL_DOUT_PIN,
                    pd_sck_pin=LOADCELL_SCK_PIN,
                    channel="A",
                    gain=64,
                )
                self.emulation = False
            except (ImportError, ModuleNotFoundError):
                logger.info("[EMULATION] LoadCell using emulated HX711")
                from emulation.hx711 import EmulatedHX711
                from hardware.loadcell import CALIBRATION_FACTOR
                self.hx711 = EmulatedHX711(calibration_factor=CALIBRATION_FACTOR)
                self._GPIO = None
                self.emulation = True
        self.offset: float = 0.0
        self.ready: bool = False

    def initialize(self) -> None:
        """Reset and calibrate the HX711. Raises RuntimeError on timeout."""
        logger.info("Calibrating...")
        state = _run_with_timeout(self.hx711.reset, 15)
        if state == -1:
            raise RuntimeError("[LoadCell] Timeout resetting HX711")
        offset = _run_with_timeout(self.get_offset, 15)
        if offset == -1:
            raise RuntimeError("[LoadCell] Timeout getting offset")
        self.offset = offset
        self.ready = True
        logger.info(f"Ready. Offset={self.offset:.1f}")

    def get_offset(self, times: int = 5) -> float:
        """Read raw HX711 values `times` times and return the average."""
        measures = []
        while len(measures) < times:
            data = self.hx711._read()
            if data is not False and data != -1:
                measures.append(data)
                logger.debug(f"Offset measure {len(measures)}/{times}")
        return sum(measures) / len(measures)

    def tare(self) -> None:
        """Re-zero the load cell: re-sample the HX711 offset so the current.

        load becomes the new zero reference, matching the original behaviour.
        """
        new_offset = _run_with_timeout(self.get_offset, 15)
        if new_offset != -1:
            self.offset = new_offset

    def get_weight(self) -> float:
        """Return the current weight in kg. Returns 0.0 on a bad read."""
        raw = self.hx711._read()
        if raw is False or raw == -1:
            return 0.0
        return (raw - self.offset) / CALIBRATION_FACTOR

    def set_weight(self, kg: float) -> None:
        """Delegate to the underlying HX711 stub (emulation only).

        Raises AttributeError if called against real hardware.
        """
        self.hx711.set_weight(kg)

    def cleanup(self) -> None:
        """Clean up GPIO resources for the load cell."""
        if hasattr(self.hx711, "power_down"):
            self.hx711.power_down()
        if hasattr(self, "_GPIO"):
            self._GPIO.cleanup()
