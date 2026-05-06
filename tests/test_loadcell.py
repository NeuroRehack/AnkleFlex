"""Unit tests for LoadCell using emulated HX711."""

import pytest

from hardware.loadcell import LoadCell


class DummyHX711:
    """Emulated HX711 for LoadCell unit tests."""

    def __init__(self):
        """Initialize DummyHX711 with default value 1234."""
        self.value = 1234

    def _read(self):
        """Return the current emulated value."""
        return self.value

    def reset(self):
        """Reset the emulated HX711 (noop)."""
        return True

    def set_weight(self, kg):
        """Set the emulated weight value."""
        self.value = kg * -1554


def test_loadcell_get_weight():
    """Test LoadCell.get_weight returns correct value."""
    hx = DummyHX711()
    lc = LoadCell(hx711=hx)
    lc.offset = 0
    assert lc.get_weight() == pytest.approx(hx.value / -1554)


def test_loadcell_set_weight():
    """Test LoadCell.set_weight sets the emulated value."""
    hx = DummyHX711()
    lc = LoadCell(hx711=hx)
    lc.set_weight(2.0)
    assert hx.value == pytest.approx(2.0 * -1554)
