import importlib

from fastapi.testclient import TestClient


def test_terrain_3d_routes_are_served(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ALLOW_MISSING_DATA", "true")

    import main

    importlib.reload(main)
    client = TestClient(main.app)

    response = client.get("/terrain-3d")
    floodmap_response = client.get("/floodmap/terrain-3d")

    assert response.status_code == 200
    assert floodmap_response.status_code == 200
    assert "FloodMap 3D" in response.text
    assert "/api${normalizedPath}" in response.text
    assert "maplibregl.setWorkerUrl(window.floodmapAssetUrl" in response.text
    assert "static/js/terrain-3d-math.js?v=20260517x" in response.text
    assert "static/js/terrain-3d-world.js?v=20260517x" in response.text
    assert "static/js/terrain-3d-flood-player.js?v=20260517x" in response.text
    assert "static/js/terrain-3d-basemap.js?v=20260517x" in response.text
    assert "static/js/terrain-3d.js?v=20260517x" in response.text
