import importlib

from fastapi.testclient import TestClient


def test_terrain_3d_routes_are_served(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ALLOW_MISSING_DATA", "true")

    import main
    import page_renderer

    importlib.reload(main)
    importlib.reload(page_renderer)
    client = TestClient(main.app)
    asset_version = page_renderer.ASSET_VERSION

    response = client.get("/terrain-3d")
    floodmap_response = client.get("/floodmap/terrain-3d")

    assert response.status_code == 200
    assert floodmap_response.status_code == 200
    assert "FloodMap 3D" in response.text
    assert "/api${normalizedPath}" in response.text
    assert "maplibregl.setWorkerUrl(window.floodmapAssetUrl" in response.text
    assert f"static/css/terrain-3d.css?v={asset_version}" in response.text
    assert f"static/js/flood-sim-core.js?v={asset_version}" in response.text
    assert f"static/js/terrain-3d-math.js?v={asset_version}" in response.text
    assert f"static/js/terrain-3d-world.js?v={asset_version}" in response.text
    assert f"static/js/terrain-3d-flood-player.js?v={asset_version}" in response.text
    assert f"static/js/terrain-3d-basemap.js?v={asset_version}" in response.text
    assert f"static/js/terrain-3d.js?v={asset_version}" in response.text
    assert 'id="exaggeration"' not in response.text
    assert "exaggeration-readout" not in response.text
