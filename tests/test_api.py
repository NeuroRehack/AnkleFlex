"""API integration tests for AnkleFlex FastAPI server."""

from fastapi.testclient import TestClient

from hardware.loadcell import LoadCell
from server.app import app, configure


class DummyHX711:
    """Emulated HX711 for API tests."""

    def __init__(self):
        """Initialize DummyHX711 with default value 0.0."""
        self.value = 0.0

    def _read(self):
        """Return the current emulated value."""
        return self.value

    def reset(self):
        """Reset the emulated HX711 (noop)."""
        return True

    def set_weight(self, kg):
        """Set the emulated weight value."""
        self.value = kg * -1554


def setup_module(module):
    """Set up the test module with an emulated LoadCell."""
    lc = LoadCell(hx711=DummyHX711())
    configure(lc, emulate=True)


client = TestClient(app)


def test_status():
    """Test the /status endpoint returns weight in response."""
    response = client.get("/status")
    assert response.status_code == 200
    assert "weight" in response.json()


def test_emulation_weight():
    """Test setting emulated weight via the API."""
    response = client.post("/emulation/weight", json={"weight": 2.0})
    assert response.status_code == 200
    assert response.json()["ok"] is True
