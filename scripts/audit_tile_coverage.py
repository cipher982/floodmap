#!/usr/bin/env python3
"""
CLI to audit elevation tile coverage for a bbox at a zoom level.

Example:
  python scripts/audit_tile_coverage.py --z 10 --bbox -82.9 24.5 -80.0 27.5
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure src/api is on path
ROOT = Path(__file__).resolve().parents[1]
SYS_PATHS = [ROOT / "src", ROOT / "src" / "api"]
for p in SYS_PATHS:
    sys.path.insert(0, str(p))

from diagnostics.tile_coverage import audit_bbox  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description="Audit elevation tile coverage over a bbox"
    )
    parser.add_argument(
        "--z",
        type=int,
        required=True,
        help="Zoom level (e.g., 10-13 for coastal debug)",
    )
    parser.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        required=True,
        metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")

    args = parser.parse_args()
    min_lon, min_lat, max_lon, max_lat = args.bbox

    report = audit_bbox(min_lon, min_lat, max_lon, max_lat, args.z)

    if args.pretty:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(json.dumps(report))


if __name__ == "__main__":
    main()
