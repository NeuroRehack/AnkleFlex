"""Unit tests for LoadCell using emulated HX711."""

import threading

import pytest

from hardware.loadcell import LoadCell


class StuckHX711:
    """HX711 stub that never returns a valid reading (simulates power-down)."""

    def _read(self):
        """Always report a failed read, like a chip stuck in power-down."""
        return False

    def reset(self):
        """Reset never succeeds while the chip is unresponsive."""
        return False


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


def test_get_weight_returns_none_on_bad_read():
    """A failed read yields None (not 0.0) so callers can detect a dead sensor."""
    lc = LoadCell(hx711=StuckHX711())
    lc.offset = 0
    assert lc.get_weight() is None


def test_get_offset_is_bounded_on_stuck_sensor():
    """get_offset must return promptly (bounded attempts), never hang."""
    lc = LoadCell(hx711=StuckHX711())

    result = {}

    def run():
        result["value"] = lc.get_offset(times=3)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=5.0)
    assert not t.is_alive(), "get_offset() hung on an unresponsive sensor"
    assert result["value"] == 0.0
