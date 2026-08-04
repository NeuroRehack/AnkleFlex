"""Real LoadCell implementation using HX711 ADC.

Only works on Raspberry Pi with the load cell hardware connected.
"""

import logging
import time
import queue
import threading

logger = logging.getLogger("ankleflex.loadcell")

LOADCELL_DOUT_PIN = 2  # GPIO 2 / Board pin 3
LOADCELL_SCK_PIN = 3  # GPIO 3 / Board pin 5
CALIBRATION_FACTOR = -1554  # Obtained from calibration script


def _run_with_timeout(func, timeout: float):
    """Run a no-argument callable in a thread with a timeout.

    Returns -1 if the timeout is exceeded, otherwise the function's result.
    Re-raises any exception thrown by func.
    """
    q: queue.Queue = queue.Queue()

    def wrapper():
        try:
            q.put((True, func()))
        except Exception as exc:  # noqa: BLE001
            q.put((False, exc))

    t = threading.Thread(target=wrapper, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return -1
    ok, value = q.get()
    if not ok:
        raise value
    return value


class LoadCell:
    """Reads force from a TAL220B load cell via HX711 ADC.

    An optional ``hx711`` argument may be passed to inject an emulated HX711
    (e.g. EmulatedHX711) instead of opening the real hardware.  All other
    logic — offset arithmetic, tare, calibration — runs unchanged either way.
    """

    def recover(self) -> bool:
        """Attempt a bounded power-cycle of the HX711. Returns True if successful.

        Delegates to the HX711's ``reset()`` (``SafeHX711`` performs a bounded
        power-down/power-up cycle that never hangs).  Serialised via the shared
        lock so it cannot run concurrently with a read.
        """
        if not hasattr(self.hx711, "reset"):
            logger.warning("[LoadCell] recover() called but HX711 has no reset() method")
            return False
        with self._lock:
            try:
                return bool(self.hx711.reset())
            except Exception as exc:
                logger.error(f"[LoadCell] HX711 recover/reset failed: {exc}")
                return False

    def __init__(self, hx711=None) -> None:
        """Initialize the LoadCell object."""
        # Serialises every access to the HX711.  The chip is driven by
        # bit-banging shared GPIO pins, so concurrent reads from the sensor
        # loop and the button/tare thread corrupt the timing and can push the
        # chip into power-down (a >60 us clock glitch).  All methods that touch
        # the chip acquire this lock so only one talks to it at a time.
        self._lock = threading.Lock()
        if hx711 is not None:
            # Emulation path: caller supplies a pre-built HX711 stub.
            self.hx711 = hx711
            self._GPIO = None
            self.emulation = True
        else:
            try:
                import RPi.GPIO as GPIO
                from hardware.safe_hx711 import SafeHX711

                self._GPIO = GPIO
                logger.info("Initializing HX711 (hardware mode)...")
                self.hx711 = SafeHX711(
                    dout_pin=LOADCELL_DOUT_PIN,
                    pd_sck_pin=LOADCELL_SCK_PIN,
                    channel="A",
                    gain=64,
                )
                # Hardware validation is deferred to initialize(), which uses
                # a 15-second timeout appropriate for the HX711 power-up cycle.
                self.emulation = False
            except (ImportError, ModuleNotFoundError):
                logger.info("[EMULATION] RPi libraries not available — using emulated HX711")
                from emulation.hx711 import EmulatedHX711

                self.hx711 = EmulatedHX711(calibration_factor=CALIBRATION_FACTOR)
                self._GPIO = None
                self.emulation = True
        self.offset: float = 0.0
        self.ready: bool = False

    def initialize(self) -> None:
        """Reset and calibrate the HX711.

        If the chip does not respond within 15 seconds (e.g. no hardware
        connected), falls back to emulation mode instead of crashing.
        """
        logger.info("Calibrating...")
        try:
            state = _run_with_timeout(self.hx711.reset, 15)
        except Exception as exc:
            logger.warning(
                "[LoadCell] HX711 reset raised an exception — falling back to emulation: %s",
                exc,
            )
            self._activate_emulation()
            return
        if state == -1:
            logger.warning(
                "[LoadCell] HX711 did not respond within 15 s — "
                "no hardware connected? Falling back to emulation."
            )
            self._activate_emulation()
            return
        try:
            offset = _run_with_timeout(self.get_offset, 15)
        except Exception as exc:
            logger.warning(
                "[LoadCell] Error reading initial offset — falling back to emulation: %s",
                exc,
            )
            self._activate_emulation()
            return
        if offset == -1:
            logger.warning("[LoadCell] Timeout reading initial offset — falling back to emulation.")
            self._activate_emulation()
            return
        self.offset = offset
        self.ready = True
        logger.info(f"Ready. Offset={self.offset:.1f}")

    def _activate_emulation(self) -> None:
        """Switch to EmulatedHX711 at runtime (called when hardware is absent)."""
        from emulation.hx711 import EmulatedHX711

        self.hx711 = EmulatedHX711(calibration_factor=CALIBRATION_FACTOR)
        self._GPIO = None
        self.emulation = True
        self.offset = 0.0
        self.ready = True

    def get_offset(self, times: int = 5, max_attempts: int | None = None) -> float:
        """Read raw HX711 values `times` times and return the average.

        Bounded so it cannot loop forever if the chip stops responding: after
        ``max_attempts`` (default ``times * 5``) tries it returns the average of
        whatever was collected, or ``0.0`` if nothing valid could be read.
        """
        if max_attempts is None:
            max_attempts = max(times * 5, times)
        measures = []
        attempts = 0
        with self._lock:
            while len(measures) < times and attempts < max_attempts:
                attempts += 1
                data = self.hx711._read()
                if data is not False and data != -1:
                    measures.append(data)
                    logger.debug(f"Offset measure {len(measures)}/{times}")
                else:
                    time.sleep(0.01)
        if not measures:
            logger.warning("[LoadCell] get_offset got no valid samples in %d attempts", attempts)
            return 0.0
        return sum(measures) / len(measures)

    def tare(self) -> None:
        """Re-zero the load cell: re-sample the HX711 offset so the current.

        load becomes the new zero reference, matching the original behaviour.
        """
        new_offset = _run_with_timeout(self.get_offset, 15)
        if new_offset != -1:
            self.offset = new_offset
        else:
            logger.warning("[LoadCell] tare timed out — offset unchanged")

    def get_weight(self) -> float | None:
        """Return the current weight in kg, or ``None`` on a bad read.

        Returning ``None`` (rather than ``0.0``) lets callers distinguish a
        genuine 0 kg reading from a failed/absent read, so a stuck sensor no
        longer masquerades as a real zero and does not pollute min/max/history.
        """
        with self._lock:
            raw = self.hx711._read()
        if raw is False or raw == -1:
            return None
        return (raw - self.offset) / CALIBRATION_FACTOR

    def set_weight(self, kg: float) -> None:
        """Delegate to the underlying HX711 stub (emulation only).

        Raises AttributeError if called against real hardware.
        """
        self.hx711.set_weight(kg)

    def get_diagnostics(self) -> dict:
        """Return low-level HX711 read/reset counters, if the driver exposes them.

        ``SafeHX711`` provides ``stats_snapshot()``; emulated/dummy backends may
        not, in which case an empty dict is returned.
        """
        snapshot = getattr(self.hx711, "stats_snapshot", None)
        if callable(snapshot):
            try:
                return snapshot()
            except Exception as exc:  # noqa: BLE001
                logger.debug("[LoadCell] stats_snapshot failed: %s", exc)
        return {}

    def cleanup(self) -> None:
        """Clean up GPIO resources for the load cell."""
        if hasattr(self.hx711, "power_down"):
            self.hx711.power_down()
        if self._GPIO is not None:
            self._GPIO.cleanup()
