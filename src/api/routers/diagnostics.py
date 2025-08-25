"""Diagnostics endpoints for programmatic tile coverage auditing."""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from diagnostics.tile_coverage import audit_bbox
from elevation_loader import elevation_loader


router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("/tile-coverage")
async def tile_coverage(
    z: int = Query(..., ge=0, le=18, description="Zoom level"),
    min_lon: float = Query(..., ge=-180, le=180),
    min_lat: float = Query(..., ge=-85.0511, le=85.0511),
    max_lon: float = Query(..., ge=-180, le=180),
    max_lat: float = Query(..., ge=-85.0511, le=85.0511),
):
    """Return a coverage report for elevation tiles within a bbox at zoom z."""
    if min_lon > max_lon or min_lat > max_lat:
        raise HTTPException(status_code=400, detail="Invalid bbox: ensure min <= max for lon/lat")

    report = audit_bbox(min_lon, min_lat, max_lon, max_lat, z)
    return report


@router.get("/tile-debug")
async def tile_debug(
    z: int = Query(..., ge=0, le=18, description="Zoom level"),
    x: int = Query(..., ge=0),
    y: int = Query(..., ge=0),
):
    """Debug a single tile: report vector presence and elevation availability."""
    lat_top, lat_bottom, lon_left, lon_right = elevation_loader.num2deg(x, y, z)
    overlap = elevation_loader.find_elevation_files_for_tile(lat_top, lat_bottom, lon_left, lon_right)

    # Vector presence (roads etc.)
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        roads = loop.run_until_complete(elevation_loader._check_vector_tile(x, y, z))
    except Exception:
        roads = False

    # Elevation extract
    arr = None
    err = None
    try:
        arr = elevation_loader.get_elevation_for_tile(x, y, z, tile_size=256)
    except Exception as e:
        err = str(e)

    resp = {
        "z": z,
        "x": x,
        "y": y,
        "bounds": {"lat_top": lat_top, "lat_bottom": lat_bottom, "lon_left": lon_left, "lon_right": lon_right},
        "overlapping_files": len(overlap),
        "roads_present": bool(roads),
        "has_elevation": arr is not None,
        "error": err,
    }

    if arr is not None:
        try:
            import numpy as np
            resp["elevation_stats"] = {
                "min": int(np.min(arr[arr != -32768])) if (arr != -32768).any() else None,
                "max": int(np.max(arr[arr != -32768])) if (arr != -32768).any() else None,
            }
        except Exception:
            pass

    return resp
