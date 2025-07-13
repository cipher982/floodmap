from fastapi.testclient import TestClient
import main
import pytest


@pytest.fixture(autouse=True)
def setup_monkeypatch(monkeypatch):
    # Ensure DEBUG_MODE so location is fixed and no IP calls
    monkeypatch.setattr(main, "DEBUG_MODE", True)

    # Mock elevation data functions to control behavior
    def mock_get_elev(lat, lon):
        # Return elevation 5 m for all points
        return 5.0

    monkeypatch.setattr(main, "get_elevation", lambda lat, lon: 5.0)
    monkeypatch.setattr(main, "get_elevation_from_memory", lambda lat, lon: 5.0)

    yield


def test_risk_endpoint_safe():
    client = TestClient(main.app)
    resp = client.get("/risk/1")
    assert resp.status_code == 200
    assert resp.json()["status"] == "safe"


def test_risk_endpoint_risk():
    client = TestClient(main.app)
    resp = client.get("/risk/10")
    assert resp.status_code == 200
    assert resp.json()["status"] == "risk"


def test_flood_tile_no_flood():
    client = TestClient(main.app)
    # tile indices for zoom 8 (0..255). Use 120,180.
    resp = client.get("/flood_tiles/1/8/120/180")
    assert resp.status_code == 204  # no flood because elevation 5>1


def test_flood_tile_flood():
    client = TestClient(main.app)
    resp = client.get("/flood_tiles/10/8/120/180")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"