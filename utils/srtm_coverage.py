#!/usr/bin/env python3
"""
Utilities to reason about SRTM 1 arc-second (1x1 degree) tile coverage.

- Parse tile IDs like n27_w080_1arc_v3 → (lat=27, lon=-80)
- Enumerate expected tile IDs for a lat/lon bbox
- Audit a directory of .tif files for missing/extra tiles relative to expected
- Detect suspicious interior holes based on neighbor presence
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

TILE_RE = re.compile(
    r"^(?P<ns>[ns])(?P<lat>\d{1,2})_(?P<ew>[ew])(?P<lon>\d{3})_1arc_v\d+", re.IGNORECASE
)


def tile_id(lat: int, lon: int, version: int = 3) -> str:
    ns = "n" if lat >= 0 else "s"
    ew = "e" if lon >= 0 else "w"
    return f"{ns}{abs(lat):02d}_{ew}{abs(lon):03d}_1arc_v{version}"


def parse_tile_id(name: str) -> tuple[int, int] | None:
    m = TILE_RE.match(Path(name).stem)
    if not m:
        return None
    lat = int(m.group("lat")) * (1 if m.group("ns").lower() == "n" else -1)
    lon = int(m.group("lon")) * (1 if m.group("ew").lower() == "e" else -1)
    return lat, lon


@dataclass(frozen=True)
class BBox:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    def normalized(self) -> BBox:
        min_lon, max_lon = sorted((self.min_lon, self.max_lon))
        min_lat, max_lat = sorted((self.min_lat, self.max_lat))
        return BBox(min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat)


def enumerate_expected_tiles(bbox: BBox) -> list[str]:
    """Enumerate all SRTM tile IDs that intersect the given bbox (inclusive).

    WARNING: This function assumes elevation data exists for ALL coordinate squares
    within the bbox, including ocean areas. SRTM only covers land areas, so this
    will report false positives for ocean-only tiles. Use with caution for auditing.
    """
    bb = bbox.normalized()
    lon0 = math.floor(bb.min_lon)
    lon1 = math.floor(bb.max_lon)
    lat0 = math.floor(bb.min_lat)
    lat1 = math.floor(bb.max_lat)
    expected: list[str] = []
    for lat in range(lat0, lat1 + 1):
        for lon in range(lon0, lon1 + 1):
            expected.append(tile_id(lat, lon))
    return expected


def find_present_tiles(
    input_dir: Path, patterns: Iterable[str] = ("*.tif", "*.TIF")
) -> set[str]:
    stems: set[str] = set()
    for pat in patterns:
        for p in input_dir.glob(pat):
            stems.add(p.stem)
    return stems


def set_from_stems(stems: Iterable[str]) -> set[tuple[int, int]]:
    coords: set[tuple[int, int]] = set()
    for s in stems:
        parsed = parse_tile_id(s)
        if parsed:
            coords.add(parsed)
    return coords


def audit_directory_against_bbox(input_dir: Path, bbox: BBox) -> dict[str, object]:
    """Audit SRTM coverage against a bounding box.

    WARNING: This will report ocean-only coordinate squares as "missing" even though
    SRTM data doesn't exist for water areas. Most "missing" tiles are false positives.
    """
    present = find_present_tiles(input_dir)
    expected = set(enumerate_expected_tiles(bbox))
    missing = sorted(expected - present)
    extra = sorted(present - expected)
    return {
        "input_dir": str(input_dir),
        "bbox": {
            "min_lon": bbox.min_lon,
            "min_lat": bbox.min_lat,
            "max_lon": bbox.max_lon,
            "max_lat": bbox.max_lat,
        },
        "expected_count": len(expected),
        "present_count": len(present),
        "missing_count": len(missing),
        "extra_count": len(extra),
        "missing": missing,
        "extra": extra,
    }


def audit_interior_holes(input_dir: Path) -> dict[str, object]:
    """Detect holes inside the rectangular envelope of present tiles.

    Returns a list of missing tile IDs within [lon_min..lon_max] x [lat_min..lat_lat_max]
    where neighbor presence suggests a gap. This does not require an external bbox.

    NOTE: This is more reliable than bbox auditing since it only looks for gaps
    within areas that should have data based on existing coverage patterns.
    """
    stems = find_present_tiles(input_dir)
    coords = set_from_stems(stems)
    if not coords:
        return {
            "input_dir": str(input_dir),
            "present_count": 0,
            "envelope_missing_count": 0,
            "envelope_missing": [],
            "suspicious_count": 0,
            "suspicious": [],
        }
    lats = [lat for lat, _ in coords]
    lons = [lon for _, lon in coords]
    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)

    envelope_expected: set[tuple[int, int]] = set(
        (lat, lon)
        for lat in range(lat_min, lat_max + 1)
        for lon in range(lon_min, lon_max + 1)
    )
    envelope_missing = sorted(envelope_expected - coords)

    def neighbor_count(lat: int, lon: int) -> int:
        neighbors = [
            (lat + 1, lon),
            (lat - 1, lon),
            (lat, lon + 1),
            (lat, lon - 1),
            (lat + 1, lon + 1),
            (lat + 1, lon - 1),
            (lat - 1, lon + 1),
            (lat - 1, lon - 1),
        ]
        return sum((n in coords) for n in neighbors)

    suspicious_coords = [
        (lat, lon) for (lat, lon) in envelope_missing if neighbor_count(lat, lon) >= 2
    ]
    suspicious_ids = [tile_id(lat, lon) for (lat, lon) in suspicious_coords]

    return {
        "input_dir": str(input_dir),
        "present_count": len(coords),
        "envelope": {
            "lat_min": lat_min,
            "lat_max": lat_max,
            "lon_min": lon_min,
            "lon_max": lon_max,
        },
        "envelope_missing_count": len(envelope_missing),
        "envelope_missing": [tile_id(lat, lon) for (lat, lon) in envelope_missing],
        "suspicious_count": len(suspicious_ids),
        "suspicious": suspicious_ids,
    }


def bbox_for_region(region: str) -> BBox:
    r = region.lower()
    if r in {"usa", "usa-conus", "conus"}:
        return BBox(min_lon=-125.0, min_lat=24.0, max_lon=-66.0, max_lat=50.0)
    if r == "florida":
        return BBox(min_lon=-88.0, min_lat=24.0, max_lon=-79.0, max_lat=31.0)
    if r == "miami":
        return BBox(min_lon=-81.0, min_lat=25.0, max_lon=-79.0, max_lat=26.5)
    raise ValueError(f"Unknown region preset: {region}")
