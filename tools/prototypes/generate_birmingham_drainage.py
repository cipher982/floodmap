from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import py3dep
import pyflwdir
import rasterio
import rasterio.features
from affine import Affine
from PIL import Image
from pynhd import NHDPlusHR
from pyproj import Transformer

WEBMERCATOR_HALF_WORLD = 20037508.342789244
TILE_SIZE = 256
NODATA_U16 = 65535
NODATA_FLOAT = -9999.0


@dataclass(frozen=True)
class PrototypeConfig:
    name: str = "birmingham-drainage"
    title: str = "Birmingham HAND Prototype"
    # Birmingham metro / Jefferson County proof bbox. Keep this modest so the
    # prototype can be regenerated quickly by an agent on a laptop.
    bbox_lonlat: tuple[float, float, float, float] = (-87.02, 33.30, -86.52, 33.75)
    dem_resolution_m: int = 10
    stream_min_order: int = 2
    stream_burn_depth_m: float = 5.0
    flow_accumulation_drain_threshold_km2: float = 1.0
    zoom_min: int = 9
    zoom_max: int = 12


CONFIG = PrototypeConfig()
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "src" / "web" / "prototypes" / CONFIG.name
TILES_DIR = OUT_DIR / "tiles"
SOURCE_DIR = ROOT / "data" / "terrain" / "hand"
SOURCE_COG_PATH = SOURCE_DIR / f"{CONFIG.name}.tif"
MODEL_PATH = OUT_DIR / "model.npz"
META_PATH = OUT_DIR / "metadata.json"
QA_PATH = OUT_DIR / "qa-report.md"
PREVIEW_PATH = OUT_DIR / "preview.png"


def mercator_to_lonlat(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lon = (x / WEBMERCATOR_HALF_WORLD) * 180.0
    lat = np.degrees(
        2.0 * np.arctan(np.exp(y / WEBMERCATOR_HALF_WORLD * math.pi)) - math.pi / 2.0
    )
    return lon, lat


def lonlat_to_mercator(
    lon: np.ndarray, lat: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    x = lon * WEBMERCATOR_HALF_WORLD / 180.0
    clipped_lat = np.clip(lat, -85.05112878, 85.05112878)
    y = np.log(np.tan((90.0 + clipped_lat) * math.pi / 360.0)) / math.pi
    y = y * WEBMERCATOR_HALF_WORLD
    return x, y


def tile_bounds_mercator(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    tiles = 2**z
    tile_span = 2 * WEBMERCATOR_HALF_WORLD / tiles
    minx = -WEBMERCATOR_HALF_WORLD + x * tile_span
    maxx = minx + tile_span
    maxy = WEBMERCATOR_HALF_WORLD - y * tile_span
    miny = maxy - tile_span
    return minx, miny, maxx, maxy


def tile_range_for_bbox(
    z: int, bbox_lonlat: tuple[float, float, float, float]
) -> tuple[range, range]:
    west, south, east, north = bbox_lonlat

    def lon_to_x_tile(lon: float) -> int:
        return int(math.floor((lon + 180.0) / 360.0 * (2**z)))

    def lat_to_y_tile(lat: float) -> int:
        lat_rad = math.radians(lat)
        return int(
            math.floor((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * (2**z))
        )

    xmin = max(0, lon_to_x_tile(west))
    xmax = min((2**z) - 1, lon_to_x_tile(east))
    ymin = max(0, lat_to_y_tile(north))
    ymax = min((2**z) - 1, lat_to_y_tile(south))
    return range(xmin, xmax + 1), range(ymin, ymax + 1)


def fetch_dem() -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    print(f"Fetching 3DEP DEM {CONFIG.dem_resolution_m}m for {CONFIG.bbox_lonlat}")
    dem_da = py3dep.get_dem(CONFIG.bbox_lonlat, resolution=CONFIG.dem_resolution_m)
    dem = np.asarray(dem_da.values, dtype=np.float32)
    x = np.asarray(dem_da.coords["x"].values, dtype=np.float64)
    y = np.asarray(dem_da.coords["y"].values, dtype=np.float64)
    crs = str(dem_da.rio.crs)
    print(f"DEM grid {dem.shape[1]} x {dem.shape[0]} in {crs}")
    return dem, x, y, crs


def fetch_flowlines(crs: str):
    print("Fetching NHDPlus HR flowlines")
    flowlines = NHDPlusHR("flowline").bygeom(CONFIG.bbox_lonlat)
    flowlines = flowlines.to_crs(crs)

    named = flowlines["gnis_name"].notna()
    order = flowlines["streamorde"].fillna(0).astype(float) >= CONFIG.stream_min_order
    in_network = flowlines["innetwork"].fillna(0).astype(float) == 1
    selected = flowlines[(named | order) & in_network].copy()
    if selected.empty:
        selected = flowlines[named | order].copy()
    selected["prototype_stream_id"] = np.arange(1, len(selected) + 1, dtype=np.int32)
    selected["prototype_name"] = selected["gnis_name"].fillna(
        selected["ftype"].fillna("Mapped drainage").astype(str)
    )
    print(f"Selected {len(selected)} of {len(flowlines)} flowlines")
    return selected


def raster_transform(x: np.ndarray, y: np.ndarray) -> Affine:
    dx = float(np.median(np.abs(np.diff(x))))
    dy = float(np.median(np.abs(np.diff(y))))
    west = float(np.min(x) - dx / 2.0)
    north = float(np.max(y) + dy / 2.0)
    return Affine.translation(west, north) * Affine.scale(dx, -dy)


def derive_drainage_height(
    dem: np.ndarray, x: np.ndarray, y: np.ndarray, flowlines
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    transform = raster_transform(x, y)
    shape = dem.shape
    valid_dem = np.isfinite(dem)

    stream_shapes = [
        (geom, int(stream_id))
        for geom, stream_id in zip(
            flowlines.geometry, flowlines["prototype_stream_id"], strict=True
        )
        if geom is not None and not geom.is_empty
    ]
    stream_id_grid = rasterio.features.rasterize(
        stream_shapes,
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype="int32",
        all_touched=True,
    )

    stream_mask = stream_id_grid > 0
    if not np.any(stream_mask):
        raise RuntimeError("No selected drainage cells were rasterized.")

    print(f"Rasterized {int(stream_mask.sum())} mapped drainage cells")

    routed_dem = np.where(valid_dem, dem, NODATA_FLOAT).astype(np.float32, copy=True)
    routed_dem[stream_mask & valid_dem] -= CONFIG.stream_burn_depth_m

    print("Deriving D8 flow directions from stream-burned DEM")
    flw = pyflwdir.from_dem(
        routed_dem,
        nodata=NODATA_FLOAT,
        transform=transform,
        latlon=False,
        outlets="edge",
    )

    print("Computing upstream area")
    upstream_area_km2 = flw.upstream_area("km2")
    accumulation_drain_mask = (
        upstream_area_km2 >= CONFIG.flow_accumulation_drain_threshold_km2
    )
    drain_mask = (stream_mask | accumulation_drain_mask) & valid_dem
    if not np.any(drain_mask):
        raise RuntimeError("No HAND drain cells were derived.")

    print(
        "HAND drain cells: "
        f"{int(np.count_nonzero(drain_mask))} total "
        f"({int(np.count_nonzero(stream_mask & valid_dem))} mapped, "
        f"{int(np.count_nonzero(accumulation_drain_mask & valid_dem))} accumulated)"
    )
    print("Computing flow-path HAND")
    hand = flw.hand(drain=drain_mask, elevtn=np.where(valid_dem, dem, NODATA_FLOAT))
    hand = np.asarray(hand, dtype=np.float32)
    hand[(~valid_dem) | (hand < 0)] = np.nan

    return hand, upstream_area_km2.astype(np.float32), drain_mask, stream_mask


def nearest_axis_indices(coords: np.ndarray, values: np.ndarray) -> np.ndarray:
    ascending = coords[0] < coords[-1]
    lookup = coords if ascending else coords[::-1]
    indices = np.searchsorted(lookup, values)
    if len(lookup) > 1:
        lower = np.clip(indices - 1, 0, len(lookup) - 1)
        upper = np.clip(indices, 0, len(lookup) - 1)
        indices = np.where(
            np.abs(lookup[lower] - values) <= np.abs(lookup[upper] - values),
            lower,
            upper,
        )
    indices = np.clip(indices, 0, len(lookup) - 1)
    return indices if ascending else (len(coords) - 1 - indices)


def sample_grid_to_tile(
    grid: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    z: int,
    tx: int,
    ty: int,
    to_grid: Transformer,
) -> np.ndarray:
    minx, miny, maxx, maxy = tile_bounds_mercator(z, tx, ty)
    web_xs = np.linspace(minx, maxx, TILE_SIZE, endpoint=False) + (maxx - minx) / (
        TILE_SIZE * 2
    )
    web_ys = np.linspace(maxy, miny, TILE_SIZE, endpoint=False) - (maxy - miny) / (
        TILE_SIZE * 2
    )
    web_x_grid, web_y_grid = np.meshgrid(web_xs, web_ys)
    grid_x, grid_y = to_grid.transform(web_x_grid, web_y_grid)

    col = nearest_axis_indices(x_coords, grid_x)
    row = nearest_axis_indices(y_coords, grid_y)
    tile = grid[row, col]
    inside = (
        (grid_x >= x_coords.min())
        & (grid_x <= x_coords.max())
        & (grid_y >= y_coords.min())
        & (grid_y <= y_coords.max())
    )
    valid = inside & np.isfinite(tile)
    safe_tile = np.where(valid, tile, 0.0)
    out = np.asarray(np.round(safe_tile * 10.0), dtype=np.uint16)
    out[out >= NODATA_U16] = NODATA_U16 - 1
    out[~valid] = NODATA_U16
    return out


def write_tiles(
    hand: np.ndarray, x: np.ndarray, y: np.ndarray, crs: str
) -> dict[str, int]:
    if TILES_DIR.exists():
        shutil.rmtree(TILES_DIR)
    TILES_DIR.mkdir(parents=True, exist_ok=True)
    to_grid = Transformer.from_crs("EPSG:3857", crs, always_xy=True)
    tile_counts: dict[str, int] = {}
    for z in range(CONFIG.zoom_min, CONFIG.zoom_max + 1):
        x_range, y_range = tile_range_for_bbox(z, CONFIG.bbox_lonlat)
        count = 0
        for tx in x_range:
            for ty in y_range:
                tile = sample_grid_to_tile(hand, x, y, z, tx, ty, to_grid)
                if np.all(tile == NODATA_U16):
                    continue
                tile_dir = TILES_DIR / str(z) / str(tx)
                tile_dir.mkdir(parents=True, exist_ok=True)
                (tile_dir / f"{ty}.u16").write_bytes(tile.tobytes())
                count += 1
        tile_counts[str(z)] = count
        print(f"z{z}: wrote {count} tiles")
    return tile_counts


def write_source_cog(hand: np.ndarray, x: np.ndarray, y: np.ndarray, crs: str) -> None:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    transform = raster_transform(x, y)
    valid = np.isfinite(hand) & (hand >= 0)
    encoded = np.full(hand.shape, NODATA_U16, dtype=np.uint16)
    encoded[valid] = np.clip(np.round(hand[valid] * 10.0), 0, NODATA_U16 - 1).astype(
        np.uint16
    )

    profile = {
        "driver": "COG",
        "height": encoded.shape[0],
        "width": encoded.shape[1],
        "count": 1,
        "dtype": "uint16",
        "crs": crs,
        "transform": transform,
        "nodata": NODATA_U16,
        "compress": "DEFLATE",
        "predictor": 2,
        "blocksize": 512,
        "overview_resampling": "nearest",
    }
    with rasterio.open(SOURCE_COG_PATH, "w", **profile) as dst:
        dst.write(encoded, 1)


def make_preview(
    hand: np.ndarray, drain_mask: np.ndarray, stream_mask: np.ndarray
) -> None:
    threshold_m = 3.0
    exposed = hand <= threshold_m
    image = np.zeros((hand.shape[0], hand.shape[1], 4), dtype=np.uint8)
    # Gray terrain context from HAND gradient.
    shade = np.clip(220 - np.nan_to_num(hand, nan=50.0) * 4, 95, 230).astype(np.uint8)
    image[..., 0] = shade
    image[..., 1] = shade
    image[..., 2] = shade
    image[..., 3] = 255
    image[exposed] = np.array([37, 99, 235, 210], dtype=np.uint8)
    image[hand <= 1.0] = np.array([29, 78, 216, 235], dtype=np.uint8)
    image[drain_mask] = np.array([14, 165, 233, 255], dtype=np.uint8)
    image[stream_mask] = np.array([7, 89, 133, 255], dtype=np.uint8)
    preview = Image.fromarray(image).convert("RGB")
    if preview.width > 900:
        height = round(preview.height * 900 / preview.width)
        preview = preview.resize((900, height), Image.Resampling.LANCZOS)
    preview = preview.quantize(colors=64, method=Image.Quantize.MEDIANCUT)
    preview.save(PREVIEW_PATH, optimize=True)


def write_metadata(
    dem: np.ndarray,
    hand: np.ndarray,
    upstream_area_km2: np.ndarray,
    drain_mask: np.ndarray,
    stream_mask: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    crs: str,
    flowlines,
    tile_counts: dict[str, int],
) -> None:
    west, south, east, north = CONFIG.bbox_lonlat
    named_counts = {
        str(name): int(count)
        for name, count in flowlines["prototype_name"]
        .value_counts()
        .head(16)
        .rename_axis("name")
        .items()
    }
    thresholds_ft = [1, 3, 6, 10, 20, 30]
    threshold_stats = {}
    total = int(np.isfinite(hand).sum())
    for ft in thresholds_ft:
        m = ft * 0.3048
        threshold_stats[str(ft)] = {
            "meters": round(m, 3),
            "cells": int(np.count_nonzero(hand <= m)),
            "percent": round(np.count_nonzero(hand <= m) * 100.0 / total, 2),
        }

    metadata = {
        "name": CONFIG.name,
        "title": CONFIG.title,
        "bbox_lonlat": [west, south, east, north],
        "dem_resolution_m": CONFIG.dem_resolution_m,
        "dem_shape": list(dem.shape),
        "dem_crs": crs,
        "dem_vertical_datum": "NAVD88 via 3DEP",
        "model": "Prototype flow-path HAND: DEM elevation minus first downstream drain elevation along D8 flowpaths.",
        "not_a_full_hand_model": True,
        "routing": {
            "library": "pyflwdir",
            "method": "from_dem D8 flow directions plus FlwdirRaster.hand",
            "stream_burn_depth_m": CONFIG.stream_burn_depth_m,
            "accumulation_drain_threshold_km2": CONFIG.flow_accumulation_drain_threshold_km2,
            "drain_cell_count": int(np.count_nonzero(drain_mask)),
            "mapped_drainage_cell_count": int(np.count_nonzero(stream_mask)),
            "accumulation_drain_cell_count": int(
                np.count_nonzero(
                    upstream_area_km2 >= CONFIG.flow_accumulation_drain_threshold_km2
                )
            ),
        },
        "stream_min_order": CONFIG.stream_min_order,
        "selected_flowline_count": int(len(flowlines)),
        "named_stream_sample": named_counts,
        "threshold_stats_ft": threshold_stats,
        "tile_counts": tile_counts,
        "sample_zoom": CONFIG.zoom_max,
        "zoom_min": CONFIG.zoom_min,
        "zoom_max": CONFIG.zoom_max,
        "generated_assets": {
            "tiles": "tiles/{z}/{x}/{y}.u16",
            "source_cog": str(SOURCE_COG_PATH.relative_to(ROOT)),
            "preview": "preview.png",
            "qa_report": "qa-report.md",
        },
    }
    META_PATH.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    names_json = json.dumps(named_counts, indent=2)
    qa = f"""# Birmingham HAND Prototype QA

## Model
- Source DEM: USGS 3DEP via py3dep, {CONFIG.dem_resolution_m}m target resolution.
- Source drainage: NHDPlus HR flowlines queried for bbox `{CONFIG.bbox_lonlat}`.
- Selected mapped drainage: named flowlines or stream order >= {CONFIG.stream_min_order}.
- Routing: pyflwdir D8 flow directions from a stream-burned DEM.
- Drain mask: selected NHDPlus HR mapped drainage OR flow accumulation >= {CONFIG.flow_accumulation_drain_threshold_km2} km².
- Derived layer: flow-path HAND, `height = DEM elevation - first downstream drain elevation`.
- This is a prototype HAND-style terrain screen, not a forecast, FEMA product, or storm-drain model.

## Coverage
- DEM grid: `{dem.shape[1]} x {dem.shape[0]}` cells.
- Selected flowlines: `{len(flowlines)}`.
- Drain cells: `{int(np.count_nonzero(drain_mask))}`.
- Tile counts: `{tile_counts}`.

## Threshold Area
| Slider | Area cells | Percent of valid HAND cells |
|---:|---:|---:|
"""
    for ft, stat in threshold_stats.items():
        qa += f"| {ft} ft | {stat['cells']} | {stat['percent']}% |\n"
    qa += f"""
## Named Drainage Sample
```json
{names_json}
```

## Visual Review Checklist
- Low-height bands should trace named creek corridors, not the whole city.
- Increasing the slider from 1ft to 10ft should widen corridors gradually.
- At 20-30ft the layer should reveal valley structure, not a sea-level bathtub.
- Remaining risk: 10m DEM + NHDPlus HR do not model storm sewers, undersized culverts, blocked drains, or pluvial street flooding.
"""
    QA_PATH.write_text(qa, encoding="utf-8")

    if MODEL_PATH.exists():
        MODEL_PATH.unlink()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dem, x, y, crs = fetch_dem()
    flowlines = fetch_flowlines(crs)
    hand, upstream_area_km2, drain_mask, stream_mask = derive_drainage_height(
        dem, x, y, flowlines
    )
    tile_counts = write_tiles(hand, x, y, crs)
    write_source_cog(hand, x, y, crs)
    make_preview(hand, drain_mask, stream_mask)
    write_metadata(
        dem,
        hand,
        upstream_area_km2,
        drain_mask,
        stream_mask,
        x,
        y,
        crs,
        flowlines,
        tile_counts,
    )
    print(f"Wrote {OUT_DIR}")


if __name__ == "__main__":
    main()
