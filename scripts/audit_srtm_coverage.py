#!/usr/bin/env python3
"""
CLI to audit SRTM 1-arcsecond coverage for a directory of raw .tif tiles.

WARNING: Bbox-based auditing will report ocean areas as "missing" even though
SRTM data doesn't exist for water. Most "missing" tiles are false positives.
Use --holes for more reliable gap detection within existing coverage areas.

Examples:
  # Audit by named region preset (will show ocean false positives)
  python scripts/audit_srtm_coverage.py --input /path/to/elevation-raw --region florida

  # Audit by explicit bbox (will show ocean false positives)
  python scripts/audit_srtm_coverage.py --input /path/to/elevation-raw --bbox -82.9 24.5 -80.0 27.5

  # Detect interior holes without a bbox (more reliable)
  python scripts/audit_srtm_coverage.py --input /path/to/elevation-raw --holes
"""

import argparse
import json
from pathlib import Path

# Local imports
from utils.srtm_coverage import (
    BBox,
    audit_directory_against_bbox,
    audit_interior_holes,
    bbox_for_region,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit SRTM tile coverage for a directory")
    p.add_argument(
        "--input", required=True, help="Directory containing SRTM .tif files"
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--region", help="Named region preset (usa, florida, miami)")
    g.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
        help="Explicit bbox",
    )
    p.add_argument(
        "--holes", action="store_true", help="Detect interior holes without bbox"
    )
    p.add_argument("--json", action="store_true", help="Output JSON report")
    return p.parse_args()


def main():
    args = parse_args()
    input_dir = Path(args.input)
    if not input_dir.exists():
        raise SystemExit(f"Input directory not found: {input_dir}")

    reports = {}
    if args.region or args.bbox:
        if args.region:
            bbox = bbox_for_region(args.region)
        else:
            bbox = BBox(*args.bbox)
        reports["bbox_audit"] = audit_directory_against_bbox(input_dir, bbox)
    if args.holes:
        reports["interior_holes"] = audit_interior_holes(input_dir)

    if not reports:
        raise SystemExit("Nothing to do. Provide --region/--bbox and/or --holes")

    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        # Human-readable summary
        if "bbox_audit" in reports:
            r = reports["bbox_audit"]
            print("=== BBox Audit ===")
            print(f"Input: {r['input_dir']}")
            b = r["bbox"]
            print(
                f"BBox: lon[{b['min_lon']},{b['max_lon']}], lat[{b['min_lat']},{b['max_lat']}]"
            )
            print(f"Expected: {r['expected_count']}, Present: {r['present_count']}")
            print(f"Missing: {r['missing_count']}")
            if r["missing_count"]:
                print("Missing IDs (first 20):")
                for m in r["missing"][:20]:
                    print(f"  - {m}")
        if "interior_holes" in reports:
            r = reports["interior_holes"]
            print("\n=== Interior Holes ===")
            print(f"Present: {r['present_count']}")
            env = r.get("envelope", {})
            if env:
                print(
                    f"Envelope lon[{env['lon_min']},{env['lon_max']}], lat[{env['lat_min']},{env['lat_max']}]"
                )
            print(f"Envelope missing: {r['envelope_missing_count']}")
            if r["suspicious_count"]:
                print(f"Suspicious holes (neighbor-supported): {r['suspicious_count']}")
                for m in r["suspicious"][:20]:
                    print(f"  - {m}")


if __name__ == "__main__":
    main()
