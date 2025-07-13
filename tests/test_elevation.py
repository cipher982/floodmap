import numpy as np
import rasterio.transform
import types

import main


def test_get_elevation_from_memory(monkeypatch):
    """Ensure elevation sampling works on an in-memory 2×2 DEM."""
    # Synthetic DEM values
    data = np.array([[10, 20], [30, 40]], dtype=np.int16)

    # Define raster bounds: upper-left corner at lon=0, lat=2 with 1° pixels
    transform = rasterio.transform.from_origin(0, 2, 1, 1)  # (west, north, xsize, ysize)

    # Monkeypatch global lists in main module
    monkeypatch.setattr(main, "tif_data", [data])
    monkeypatch.setattr(main, "tif_transform", [transform])

    # Bounds
    class Bounds:
        left = 0
        right = 2
        bottom = 0
        top = 2
    monkeypatch.setattr(main, "tif_bounds", [Bounds])

    # Query each center of pixel
    tests = [
        (1.5, 0.5, 10),  # row0 col0
        (1.5, 1.5, 20),  # row0 col1
        (0.5, 0.5, 30),  # row1 col0
        (0.5, 1.5, 40),  # row1 col1
    ]

    for lat, lon, expected in tests:
        elev = main.get_elevation_from_memory(lat, lon)
        assert elev == expected, f"Expected {expected} at ({lat},{lon}), got {elev}"