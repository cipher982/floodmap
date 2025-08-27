#!/usr/bin/env python3
"""
Given lat/lon coordinates, print the corresponding SRTM 1° tile IDs and
check for file existence in a target directory.

Examples:
  python scripts/coords_to_srtm.py --coords 29.8717 -85.1726 32.5268 -82.5005 27.3559 -80.6764 \
    --dir ARCHIVED_DATA/elevation-raw
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import List, Tuple


def srtm_index(lat: float, lon: float) -> Tuple[int, int]:
    # SRTM tiles are named by the integer-degree of their SW corner.
    # Use floor for both lat and lon, including negatives.
    return (math.floor(lat), math.floor(lon))


def srtm_id(lat_i: int, lon_i: int, version: int = 3) -> str:
    ns = 'n' if lat_i >= 0 else 's'
    ew = 'e' if lon_i >= 0 else 'w'
    return f"{ns}{abs(lat_i):02d}_{ew}{abs(lon_i):03d}_1arc_v{version}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert coordinates to SRTM tile IDs and verify presence")
    ap.add_argument('--coords', type=float, nargs='+', required=True, metavar=('LAT','LON'),
                    help='List of lat lon pairs (e.g., 29.87 -85.17 32.52 -82.50)')
    ap.add_argument('--dir', type=Path, required=True, help='Directory containing SRTM GeoTIFFs or compressed tiles')
    args = ap.parse_args()

    vals = args.coords
    if len(vals) % 2 != 0:
        raise SystemExit('Provide an even number of values for --coords (lat lon pairs)')

    pairs: List[Tuple[float,float]] = [(vals[i], vals[i+1]) for i in range(0, len(vals), 2)]
    seen = set()
    for lat, lon in pairs:
        lat_i, lon_i = srtm_index(lat, lon)
        tid = srtm_id(lat_i, lon_i)
        if tid in seen:
            continue
        seen.add(tid)

        # Check both raw GeoTIFF and compressed formats
        tif = args.dir / f"{tid}.tif"
        zst = args.dir / f"{tid}.zst"
        status = 'MISSING'
        if tif.exists():
            status = 'tif'
        elif zst.exists():
            status = 'zst'

        print(f"{lat:8.4f},{lon:9.4f} -> {tid} [{status}]")


if __name__ == '__main__':
    main()

