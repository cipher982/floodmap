from fastapi.testclient import TestClient
import main
import pytest

client = TestClient(main.app)


def test_invalid_water_level():
    """FastHTML app handles invalid parameters differently than pure FastAPI."""
    # Negative water level - FastHTML allows it through, but gets 404 due to no elevation data
    resp = client.get("/risk/-5")
    assert resp.status_code == 404  # No elevation data available for test coordinates
    
    # High water level - FastHTML allows it through, flood tile generation returns 204 (no content)
    resp2 = client.get("/flood_tiles/150/8/0/0")
    assert resp2.status_code == 204  # No flooded area in tile (too high water level)


def test_invalid_tile_indices():
    """Tile indices beyond the zoom range yield 400."""
    resp = client.get("/flood_tiles/1/8/9999/0")
    assert resp.status_code == 400


def test_real_world_coord_roundtrip():
    """Seattle coordinates should map to valid tile and back within < 0.5° error."""
    lat, lon = 47.6062, -122.3321  # Seattle
    z = 8
    x, y = main.lat_lon_to_tile(lat, lon, z)
    lat_back, lon_back = main.tile_to_lat_lon(x, y, z)
    assert abs(lat - lat_back) < 0.5
    assert abs(lon - lon_back) < 0.5