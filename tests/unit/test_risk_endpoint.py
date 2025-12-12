from __future__ import annotations

import math

import numpy as np


async def test_risk_location_samples_point_pixel(monkeypatch):
    from routers import risk

    lat = 41.4381
    lon = -93.5892
    water_level_m = 1.0

    # Match the router's sampling math to pick the expected within-tile pixel.
    zoom = 11
    lat_rad = math.radians(lat)
    n = 2.0**zoom
    x_float = (lon + 180.0) / 360.0 * n
    y_float = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    x_tile = int(x_float)
    y_tile = int(y_float)
    px = min(255, max(0, int((x_float - x_tile) * 256)))
    py = min(255, max(0, int((y_float - y_tile) * 256)))

    arr = np.full((256, 256), -32768, dtype=np.int16)
    arr[py, px] = 10

    def fake_get_elevation_for_tile(x, y, z, tile_size=256):
        assert z == zoom
        assert x == x_tile
        assert y == y_tile
        return arr

    monkeypatch.setattr(
        risk.elevation_loader, "get_elevation_for_tile", fake_get_elevation_for_tile
    )

    req = risk.LocationRequest.model_validate(
        {"latitude": lat, "longitude": lon, "waterLevelM": water_level_m}
    )
    resp = await risk.assess_flood_risk(req)

    assert resp.elevation_m == 10.0
    assert resp.water_level_m == water_level_m
    assert resp.flood_risk_level == "low"


async def test_risk_location_water_point_returns_water(monkeypatch):
    from routers import risk

    lat = 47.5047
    lon = -86.5294

    # Surrounding tile has some land elevations, but sampled point is NODATA.
    arr = np.full((256, 256), -32768, dtype=np.int16)
    arr[0, 0] = 10

    def fake_get_elevation_for_tile(x, y, z, tile_size=256):
        return arr

    monkeypatch.setattr(
        risk.elevation_loader, "get_elevation_for_tile", fake_get_elevation_for_tile
    )

    req = risk.LocationRequest.model_validate({"latitude": lat, "longitude": lon})
    resp = await risk.assess_flood_risk(req)

    assert resp.flood_risk_level == "water"
    assert resp.elevation_m is None
