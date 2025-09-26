#!/usr/bin/env python3
"""
Generate comprehensive pre-compressed tiles on VPS using existing elevation data.
Run this script inside the VPS container to avoid network transfers.
"""

import gzip
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

# Add src/api to path
sys.path.insert(0, "/app/src/api")

try:
    import brotli

    print("Brotli available")
except ImportError:
    brotli = None
    print("Brotli not available")

from config import NODATA_VALUE, TILE_SIZE
from elevation_loader import elevation_loader

# Create output directory
output_dir = Path("/mnt/backup/floodmap/elevation-tiles")
output_dir.mkdir(parents=True, exist_ok=True)

print(f"Starting full tile generation at {time.strftime('%Y-%m-%d %H:%M:%S')}")

# Process ALL zoom levels with comprehensive coverage
zoom_levels = [8, 9, 10, 11, 12, 13, 14, 15]
tiles_per_zoom = 500

# Major US cities for comprehensive coverage
sample_locations = [
    (40.7128, -74.0060),
    (34.0522, -118.2437),
    (41.8781, -87.6298),
    (29.7604, -95.3698),
    (25.7617, -80.1918),
    (47.6062, -122.3321),
    (33.4484, -112.0740),
    (39.7392, -104.9903),
    (32.7767, -96.7970),
    (42.3601, -71.0589),
    (36.1627, -86.7816),
    (35.2271, -80.8431),
    (30.2672, -97.7431),
    (39.9526, -75.1652),
    (26.1224, -80.1373),
    (45.5152, -122.6784),
    (37.7749, -122.4194),
    (32.2226, -110.9747),
    (35.0853, -106.6056),
    (44.9778, -93.2650),
]


def deg2num(lat_deg, lon_deg, zoom):
    lat_rad = math.radians(lat_deg)
    n = 2.0**zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (xtile, ytile)


def generate_tile_data(z, x, y):
    try:
        elevation_data = elevation_loader.get_elevation_for_tile(
            x, y, z, tile_size=TILE_SIZE
        )
        if elevation_data is None:
            empty_data = np.full((TILE_SIZE, TILE_SIZE), 65535, dtype=np.uint16)
            return empty_data.tobytes()

        normalized = np.zeros_like(elevation_data, dtype=np.float32)
        nodata_mask = (
            (elevation_data == NODATA_VALUE)
            | (elevation_data < -500)
            | (elevation_data > 9000)
        )
        valid_mask = ~nodata_mask
        normalized[valid_mask] = np.clip(
            (elevation_data[valid_mask] + 500) / 9500 * 65534, 0, 65534
        )
        normalized[nodata_mask] = 65535
        return normalized.astype(np.uint16).tobytes()
    except Exception as e:
        print(f"Error generating tile {z}/{x}/{y}: {e}")
        empty_data = np.full((TILE_SIZE, TILE_SIZE), 65535, dtype=np.uint16)
        return empty_data.tobytes()


generated_tiles = []
start_time = time.time()

for zoom in zoom_levels:
    print(f"Processing zoom level {zoom} at {time.strftime('%H:%M:%S')}")
    tiles_generated = 0

    for lat, lon in sample_locations:
        if tiles_generated >= tiles_per_zoom:
            break

        x, y = deg2num(lat, lon, zoom)
        lat_top, lat_bottom, lon_left, lon_right = elevation_loader.num2deg(x, y, zoom)
        overlapping_files = elevation_loader.find_elevation_files_for_tile(
            lat_top, lat_bottom, lon_left, lon_right
        )

        if overlapping_files:
            tile_data = generate_tile_data(zoom, x, y)
            if tile_data and len(tile_data) > 0:
                tile_dir = output_dir / str(zoom) / str(x)
                tile_dir.mkdir(parents=True, exist_ok=True)
                base_path = tile_dir / str(y)

                with open(f"{base_path}.u16", "wb") as f:
                    f.write(tile_data)

                if brotli:
                    compressed_br = brotli.compress(tile_data, quality=1)
                    with open(f"{base_path}.u16.br", "wb") as f:
                        f.write(compressed_br)

                compressed_gz = gzip.compress(tile_data, compresslevel=1)
                with open(f"{base_path}.u16.gz", "wb") as f:
                    f.write(compressed_gz)

                generated_tiles.append((zoom, x, y))
                tiles_generated += 1

                if tiles_generated % 50 == 0:
                    elapsed = time.time() - start_time
                    print(
                        f"Generated {tiles_generated} tiles for zoom {zoom} ({elapsed:.1f}s elapsed)"
                    )

manifest = {
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "tile_count": len(generated_tiles),
    "compression_variants": ["raw", "br", "gz"],
    "tiles": generated_tiles,
    "total_time_seconds": time.time() - start_time,
}

with open(output_dir / "manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)

elapsed_total = time.time() - start_time
print(
    f"VPS generation complete! Generated {len(generated_tiles)} tiles in {elapsed_total:.1f} seconds"
)
