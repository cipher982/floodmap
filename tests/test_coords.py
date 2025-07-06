import math
import pytest
import random

from main import lat_lon_to_tile, tile_to_lat_lon


@pytest.mark.parametrize(
    "lat,lon,zoom",
    [
        (0.0, 0.0, 8),
        (37.7749, -122.4194, 9),  # San Francisco
        (-33.8688, 151.2093, 9),  # Sydney
        (51.5074, -0.1278, 8),    # London
    ],
)
def test_latlon_tile_roundtrip(lat: float, lon: float, zoom: int):
    """Converting lat/lon → tile → lat/lon should stay within half-tile error."""
    x, y = lat_lon_to_tile(lat, lon, zoom)

    # Convert the tile origin back to lat/lon
    lat_back, lon_back = tile_to_lat_lon(x, y, zoom)

    # Tile angular size in degrees at this zoom (approx)
    n = 2 ** zoom
    lon_per_tile = 360 / n
    lat_per_tile = 170.10225756 / n  # 85.0511° north to south (mercator limit)

    assert abs(lat - lat_back) <= lat_per_tile, "Latitude deviation exceeds one tile"
    assert abs(lon - lon_back) <= lon_per_tile, "Longitude deviation exceeds one tile"


def test_tile_consistency_random():
    """Random points should yield identical tile indices via double conversion."""
    rng = random.random
    for _ in range(100):
        lat = rng() * 170 - 85  # [-85, +85]
        lon = rng() * 360 - 180
        zoom = 8
        x1, y1 = lat_lon_to_tile(lat, lon, zoom)
        lat_back, lon_back = tile_to_lat_lon(x1, y1, zoom)
        x2, y2 = lat_lon_to_tile(lat_back, lon_back, zoom)
        assert (x1, y1) == (x2, y2)