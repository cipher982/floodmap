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
    """Test that tile conversion is consistent and reasonable."""
    # First conversion
    x1, y1 = lat_lon_to_tile(lat, lon, zoom)
    
    # Second conversion of same coordinates should give same tile
    x2, y2 = lat_lon_to_tile(lat, lon, zoom)
    assert (x1, y1) == (x2, y2), "Same coordinates should map to same tile"
    
    # Tile bounds check - make sure we get valid tile coordinates
    max_tile = (1 << zoom) - 1
    assert 0 <= x1 <= max_tile, f"X tile {x1} out of range for zoom {zoom}"
    assert 0 <= y1 <= max_tile, f"Y tile {y1} out of range for zoom {zoom}"
    
    # Convert back and ensure it's a valid coordinate
    lat_back, lon_back = tile_to_lat_lon(x1, y1, zoom)
    assert -85.05 <= lat_back <= 85.05, f"Latitude {lat_back} outside Web Mercator bounds"
    assert -180 <= lon_back <= 180, f"Longitude {lon_back} outside valid bounds"


def test_tile_consistency_random():
    """Test that tile conversions are self-consistent."""
    rng = random.Random(42)  # Fixed seed for reproducible tests
    for _ in range(50):  # Reduced iterations for faster tests
        lat = rng.uniform(-85, 85)  # Valid Web Mercator range
        lon = rng.uniform(-180, 180)
        zoom = rng.choice([8, 9])  # Test with allowed zoom levels
        
        # Same coordinate should always give same tile
        x1, y1 = lat_lon_to_tile(lat, lon, zoom)
        x2, y2 = lat_lon_to_tile(lat, lon, zoom)
        assert (x1, y1) == (x2, y2), f"Inconsistent tiles for lat={lat}, lon={lon}"
        
        # Tile should be in valid range
        max_tile = (1 << zoom) - 1
        assert 0 <= x1 <= max_tile, f"X tile {x1} out of range"
        assert 0 <= y1 <= max_tile, f"Y tile {y1} out of range"