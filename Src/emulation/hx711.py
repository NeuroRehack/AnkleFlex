"""
Emulated HX711 — replaces the hardware ADC for development on non-Pi systems.

Provides the same interface used by LoadCell (_read, reset) so that the real
LoadCell class can run completely unchanged in emulation mode.

The slider value (in kg) is converted to synthetic raw ADC counts using the
same CALIBRATION_FACTOR as the hardware, so all arithmetic inside LoadCell
(get_offset, get_weight, tare) produces correct results automatically.
"""

import logging

logger = logging.getLogger("ankleflex.emulation.hx711")


class EmulatedHX711:
    """Drop-in for hx711.HX711. Converts a slider kg value to raw ADC counts."""

    def __init__(self, calibration_factor: float) -> None:
        self._calibration_factor = calibration_factor
        self._weight_kg: float = 0.0
        logger.info("[EmulatedHX711] initialized (calibration_factor=%s)", calibration_factor)

    def reset(self) -> bool:
        """No-op reset — returns True immediately (hardware reset takes ~15 s)."""
        logger.info("[EmulatedHX711] reset (no-op)")
        return True

    def _read(self) -> float:
        """Return synthetic raw ADC counts equivalent to the current slider position.

        Inverse of LoadCell.get_weight():
            weight_kg = (raw - offset) / CALIBRATION_FACTOR
        so at offset=0:
            raw = weight_kg * CALIBRATION_FACTOR
        """
        raw = self._weight_kg * self._calibration_factor
        logger.debug("[EmulatedHX711] _read()  %.1f (weight=%.2f kg)", raw, self._weight_kg)
        return raw

    def set_weight(self, kg: float) -> None:
        """Set the simulated physical load in kg (called by the UI slider endpoint)."""
        self._weight_kg = float(kg)
        logger.info("[EmulatedHX711] weight set to %.2f kg", self._weight_kg)
