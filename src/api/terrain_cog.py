"""COG-backed terrain tile rendering primitives."""

from __future__ import annotations

import time
from functools import lru_cache
from math import atan, degrees, exp, pi
from pathlib import Path

import numpy as np
from terrain import (
    TILE_SIZE,
    U16_NODATA,
    U16_TILE_BYTES,
    TerrainEncoding,
    encode_elevation_meters,
)

WEBMERCATOR_HALF_WORLD = 20037508.342789244
WEBMERCATOR_CRS = "EPSG:3857"


def tile_bounds_mercator(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    tiles = 2**z
    span = 2 * WEBMERCATOR_HALF_WORLD / tiles
    minx = -WEBMERCATOR_HALF_WORLD + x * span
    maxx = minx + span
    maxy = WEBMERCATOR_HALF_WORLD - y * span
    miny = maxy - span
    return minx, miny, maxx, maxy


def mercator_to_lonlat(x: float, y: float) -> tuple[float, float]:
    lon = x / WEBMERCATOR_HALF_WORLD * 180.0
    lat = degrees(2.0 * atan(exp(y / WEBMERCATOR_HALF_WORLD * pi)) - pi / 2.0)
    return lon, lat


def tile_bbox_lonlat(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = tile_bounds_mercator(z, x, y)
    west, south = mercator_to_lonlat(minx, miny)
    east, north = mercator_to_lonlat(maxx, maxy)
    return west, south, east, north


def tile_transform_mercator(z: int, x: int, y: int):
    from affine import Affine

    minx, miny, maxx, maxy = tile_bounds_mercator(z, x, y)
    return Affine.translation(minx, maxy) * Affine.scale(
        (maxx - minx) / TILE_SIZE,
        -(maxy - miny) / TILE_SIZE,
    )


def tile_center_points_mercator(
    z: int, x: int, y: int
) -> tuple[np.ndarray, np.ndarray]:
    minx, miny, maxx, maxy = tile_bounds_mercator(z, x, y)
    pixel_span_x = (maxx - minx) / TILE_SIZE
    pixel_span_y = (maxy - miny) / TILE_SIZE
    xs = minx + (np.arange(TILE_SIZE, dtype=np.float64) + 0.5) * pixel_span_x
    ys = maxy - (np.arange(TILE_SIZE, dtype=np.float64) + 0.5) * pixel_span_y
    return np.meshgrid(xs, ys)


def render_cog_tile(
    cog_path: Path,
    z: int,
    x: int,
    y: int,
    encoding: TerrainEncoding = TerrainEncoding.HAND_DECIMETERS,
) -> tuple[bytes, float]:
    try:
        import rasterio
        from rasterio.warp import transform
        from rasterio.windows import Window
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("rasterio is required for COG terrain rendering") from exc

    start = time.perf_counter()
    destination = np.full((TILE_SIZE, TILE_SIZE), U16_NODATA, dtype=np.uint16)

    with rasterio.open(cog_path) as src:
        if src.crs is None:
            raise RuntimeError(f"Terrain source has no CRS: {cog_path}")
        web_x, web_y = tile_center_points_mercator(z, x, y)
        source_x, source_y = transform(
            WEBMERCATOR_CRS,
            src.crs,
            web_x.ravel(),
            web_y.ravel(),
        )
        inv_transform = ~src.transform
        cols_float, rows_float = inv_transform * (
            np.asarray(source_x),
            np.asarray(source_y),
        )
        rows = np.floor(rows_float).astype(np.int64)
        cols = np.floor(cols_float).astype(np.int64)
        inside = (rows >= 0) & (cols >= 0) & (rows < src.height) & (cols < src.width)

        if np.any(inside):
            row_min = int(rows[inside].min())
            row_max = int(rows[inside].max())
            col_min = int(cols[inside].min())
            col_max = int(cols[inside].max())
            window = Window.from_slices((row_min, row_max + 1), (col_min, col_max + 1))
            source = src.read(1, window=window)
            sampled = source[rows[inside] - row_min, cols[inside] - col_min]
            if src.nodata is None:
                valid_sample = np.isfinite(sampled)
            else:
                valid_sample = np.isfinite(sampled) & (sampled != src.nodata)
            if encoding == TerrainEncoding.ELEVATION_METER_RANGE:
                encoded = encode_elevation_meters(
                    np.where(valid_sample, sampled, np.nan)
                )
            else:
                encoded = sampled.astype(np.uint16, copy=False)

            output = destination.ravel()
            inside_indices = np.flatnonzero(inside)
            output[inside_indices[valid_sample]] = encoded[valid_sample]

    payload = destination.tobytes()
    if len(payload) != U16_TILE_BYTES:
        raise RuntimeError(f"Unexpected terrain tile byte length: {len(payload)}")
    elapsed_ms = (time.perf_counter() - start) * 1000
    return payload, elapsed_ms


@lru_cache(maxsize=512)
def render_cog_tile_cached(
    cog_path: str, mtime_ns: int, z: int, x: int, y: int, encoding: TerrainEncoding
) -> bytes:
    del mtime_ns  # Cache key invalidates when the source file changes.
    payload, _ = render_cog_tile(Path(cog_path), z, x, y, encoding)
    return payload


def render_cog_tile_with_cache(
    cog_path: Path,
    z: int,
    x: int,
    y: int,
    encoding: TerrainEncoding = TerrainEncoding.HAND_DECIMETERS,
) -> tuple[bytes, str, float]:
    start = time.perf_counter()
    before = render_cog_tile_cached.cache_info().hits
    stat = cog_path.stat()
    payload = render_cog_tile_cached(str(cog_path), stat.st_mtime_ns, z, x, y, encoding)
    after = render_cog_tile_cached.cache_info().hits
    elapsed_ms = (time.perf_counter() - start) * 1000
    cache_status = "HIT" if after > before else "MISS"
    return payload, cache_status, elapsed_ms


def sample_cog_point(cog_path: Path, lon: float, lat: float) -> int | None:
    try:
        import rasterio
        from rasterio.warp import transform
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("rasterio is required for COG terrain sampling") from exc

    with rasterio.open(cog_path) as src:
        xs, ys = transform("EPSG:4326", src.crs, [lon], [lat])
        row, col = src.index(xs[0], ys[0])
        if row < 0 or col < 0 or row >= src.height or col >= src.width:
            return None
        value = int(src.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
        if value == int(U16_NODATA):
            return None
        return value


def clear_cog_tile_cache() -> None:
    render_cog_tile_cached.cache_clear()
