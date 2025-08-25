import math
import asyncio
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any

from elevation_loader import elevation_loader


@dataclass
class TileCoord:
    z: int
    x: int
    y: int


@dataclass
class TileStatus:
    coord: TileCoord
    has_elevation: bool
    overlapping_files: int
    bounds: Tuple[float, float, float, float]
    note: Optional[str] = None
    roads_present: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "z": self.coord.z,
            "x": self.coord.x,
            "y": self.coord.y,
            "has_elevation": self.has_elevation,
            "overlapping_files": self.overlapping_files,
            "bounds": {
                "lat_top": self.bounds[0],
                "lat_bottom": self.bounds[1],
                "lon_left": self.bounds[2],
                "lon_right": self.bounds[3],
            },
            "note": self.note,
            "roads_present": self.roads_present,
        }


def bbox_to_tiles(min_lon: float, min_lat: float, max_lon: float, max_lat: float, z: int) -> List[TileCoord]:
    """Convert a lat/lon bbox to a list of tile coords at zoom z (inclusive)."""
    # clamp inputs
    min_lat = max(-85.05112878, min(85.05112878, min_lat))
    max_lat = max(-85.05112878, min(85.05112878, max_lat))
    min_lon = max(-180.0, min(180.0, min_lon))
    max_lon = max(-180.0, min(180.0, max_lon))

    def deg2num(lat_deg: float, lon_deg: float, zoom: int) -> Tuple[int, int]:
        lat_rad = math.radians(lat_deg)
        n = 2.0 ** zoom
        xtile = int((lon_deg + 180.0) / 360.0 * n)
        ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        return xtile, ytile

    x_min, y_max = deg2num(min_lat, min_lon, z)
    x_max, y_min = deg2num(max_lat, max_lon, z)

    x0, x1 = min(x_min, x_max), max(x_min, x_max)
    y0, y1 = min(y_min, y_max), max(y_min, y_max)

    tiles: List[TileCoord] = []
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            tiles.append(TileCoord(z, x, y))
    return tiles


def inspect_tile(coord: TileCoord) -> TileStatus:
    """Check what elevation files overlap and whether we can extract data. Also check vector presence (roads)."""
    z, x, y = coord.z, coord.x, coord.y
    lat_top, lat_bottom, lon_left, lon_right = elevation_loader.num2deg(x, y, z)
    overlapping = elevation_loader.find_elevation_files_for_tile(lat_top, lat_bottom, lon_left, lon_right)

    # Check whether vector tile appears to have features (roads etc.)
    roads_present = False
    try:
        loop = asyncio.get_event_loop()
        roads_present = loop.run_until_complete(elevation_loader._check_vector_tile(x, y, z))
    except Exception:
        roads_present = False

    note = None
    has = False
    if overlapping:
        try:
            arr = elevation_loader.get_elevation_for_tile(x, y, z, tile_size=256)
            has = arr is not None
            if not has:
                note = "overlap-no-extract"
        except Exception as e:
            has = False
            note = f"error:{type(e).__name__}"
    else:
        note = "no-overlap"

    return TileStatus(
        coord=coord,
        has_elevation=has,
        overlapping_files=len(overlapping),
        bounds=(lat_top, lat_bottom, lon_left, lon_right),
        note=note,
        roads_present=roads_present,
    )


def summarize(statuses: List[TileStatus]) -> Dict[str, Any]:
    total = len(statuses)
    have = sum(1 for s in statuses if s.has_elevation)
    with_overlap = sum(1 for s in statuses if s.overlapping_files > 0)
    no_overlap = sum(1 for s in statuses if s.overlapping_files == 0)
    errors = [s for s in statuses if s.note and s.note.startswith("error:")]
    overlap_no_extract = [s for s in statuses if s.note == "overlap-no-extract"]
    suspect_gaps = [s for s in statuses if s.roads_present and not s.has_elevation]

    return {
        "total": total,
        "have_elevation": have,
        "coverage_pct": (have / total) if total else 0.0,
        "with_overlap": with_overlap,
        "no_overlap": no_overlap,
        "overlap_no_extract": [
            {"z": s.coord.z, "x": s.coord.x, "y": s.coord.y, "files": s.overlapping_files}
            for s in overlap_no_extract
        ],
        "errors": [
            {"z": s.coord.z, "x": s.coord.x, "y": s.coord.y, "note": s.note}
            for s in errors
        ],
        "suspect_gaps": [
            {"z": s.coord.z, "x": s.coord.x, "y": s.coord.y, "note": s.note}
            for s in suspect_gaps
        ],
    }


def audit_bbox(min_lon: float, min_lat: float, max_lon: float, max_lat: float, z: int) -> Dict[str, Any]:
    tiles = bbox_to_tiles(min_lon, min_lat, max_lon, max_lat, z)
    statuses = [inspect_tile(t) for t in tiles]
    report = summarize(statuses)
    report["z"] = z
    report["bbox"] = {
        "min_lon": min_lon,
        "min_lat": min_lat,
        "max_lon": max_lon,
        "max_lat": max_lat,
    }
    return report
