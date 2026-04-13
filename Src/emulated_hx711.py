"""
Emulated HX711 — replaces the hardware ADC for development on non-Pi systems.

Provides the same interface used by LoadCell (_read, reset) so that the real
LoadCell class can run completely unchanged in emulation mode.

The slider value (in kg) is converted to synthetic raw ADC counts using the
same CALIBRATION_FACTOR as the hardware, so all arithmetic inside LoadCell
(get_offset, tare, get_weight) produces correct results automatically.
"""
import logging


class EmulatedHX711:
    """Drop-in for hx711.HX711. Converts a kg value to raw ADC counts."""

    CALIBRATION_FACTOR = -1554  # Must match main.py CALIBRATION_FACTOR

    def __init__(self) -> None:
        self._weight_kg: float = 0.0
        logging.info("[EmulatedHX711] initialized")

    def reset(self) -> bool:
        """No-op reset — returns True immediately (hardware reset takes ~15 s)."""
        logging.info("[EmulatedHX711] reset (no-op)")
        return True

    def _read(self) -> float:
        """Return synthetic raw ADC counts equivalent to the current weight.

        Inverse of LoadCell.get_weight():
            weight_kg = (raw - offset) / CALIBRATION_FACTOR
        so at offset=0:
            raw = weight_kg * CALIBRATION_FACTOR
        """
        raw = self._weight_kg * self.CALIBRATION_FACTOR
        logging.debug("[EmulatedHX711] _read() -> %.1f  (weight=%.2f kg)", raw, self._weight_kg)
        return raw

    def set_weight(self, kg: float) -> None:
        """Set the simulated physical load in kg (called by the UI slider)."""
        self._weight_kg = float(kg)
        logging.info("[EmulatedHX711] weight set to %.2f kg", self._weight_kg)

    def power_down(self) -> None:
        """No-op — satisfies LoadCell.cleanup()."""
        pass
