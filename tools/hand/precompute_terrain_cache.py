#!/usr/bin/env python3
"""Precompute v2 terrain cache tiles from a source COG manifest region."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "api"))
sys.path.insert(0, str(ROOT / "tools" / "hand"))

from config import TERRAIN_TILE_CACHE_DIR  # noqa: E402
from routers.terrain_v2 import (  # noqa: E402
    get_terrain_manifest,
    require_region_source_path,
)
from storage_estimator import format_bytes  # noqa: E402
from terrain import U16_NODATA  # noqa: E402
from terrain_cache import TerrainTileCache  # noqa: E402
from terrain_cog import clear_cog_tile_cache, render_cog_tile_with_cache  # noqa: E402


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    lat = max(min(lat, 85.05112878), -85.05112878)
    scale = 2**z
    x = math.floor((lon + 180.0) / 360.0 * scale)
    lat_rad = math.radians(lat)
    y = math.floor((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * scale)
    return x, y


def iter_tiles_for_bbox(
    bbox: tuple[float, float, float, float], min_zoom: int, max_zoom: int
) -> list[tuple[int, int, int]]:
    west, south, east, north = bbox
    tiles: list[tuple[int, int, int]] = []
    for z in range(min_zoom, max_zoom + 1):
        x0, y_top = lonlat_to_tile(west, north, z)
        x1, y_bottom = lonlat_to_tile(east, south, z)
        max_coord = (2**z) - 1
        for x in range(max(0, x0), min(max_coord, x1) + 1):
            for y in range(max(0, y_top), min(max_coord, y_bottom) + 1):
                tiles.append((z, x, y))
    return tiles


def precompute_region(args: argparse.Namespace) -> dict[str, int | str | float]:
    manifest = get_terrain_manifest()
    layer = manifest.layers.get(args.layer)
    if layer is None:
        raise SystemExit(f"Unknown terrain layer: {args.layer}")
    region = next(
        (candidate for candidate in layer.regions if candidate.id == args.region_id),
        None,
    )
    if region is None:
        raise SystemExit(f"Unknown region for layer {args.layer}: {args.region_id}")

    cache = TerrainTileCache(args.cache_dir)
    source_path = (
        None
        if args.dry_run
        else require_region_source_path(manifest, args.layer, region)
    )
    tiles = iter_tiles_for_bbox(region.bbox, args.min_zoom, args.max_zoom)
    if args.limit:
        tiles = tiles[: args.limit]

    clear_cog_tile_cache()
    stats: dict[str, int | str | float] = {
        "layer": args.layer,
        "dataset_version": manifest.dataset_version,
        "region_id": region.id,
        "source": region.url if source_path is None else str(source_path),
        "cache_dir": str(args.cache_dir),
        "candidate_tiles": len(tiles),
        "written": 0,
        "existing": 0,
        "empty_skipped": 0,
        "compressed_bytes": 0,
        "max_render_ms": 0.0,
    }

    for z, x, y in tiles:
        if cache.br_path(args.layer, manifest.dataset_version, z, x, y).exists():
            stats["existing"] = int(stats["existing"]) + 1
            if not args.overwrite:
                continue

        if args.dry_run:
            continue

        if source_path is None:
            raise RuntimeError("source path unexpectedly absent outside dry-run")
        payload, _, elapsed_ms = render_cog_tile_with_cache(source_path, z, x, y)
        values = np.frombuffer(payload, dtype=np.uint16)
        data_status = "source-nodata" if np.all(values == U16_NODATA) else "ok"
        if args.skip_empty and data_status == "source-nodata":
            stats["empty_skipped"] = int(stats["empty_skipped"]) + 1
            continue

        path = cache.write_tile(
            args.layer,
            manifest.dataset_version,
            z,
            x,
            y,
            payload,
            data_status,
        )
        stats["written"] = int(stats["written"]) + 1
        stats["compressed_bytes"] = int(stats["compressed_bytes"]) + path.stat().st_size
        stats["max_render_ms"] = max(float(stats["max_render_ms"]), elapsed_ms)

    cache_stats = cache.stats(args.layer, manifest.dataset_version)
    stats["cache_tiles_total"] = cache_stats.tile_count
    stats["cache_bytes_total"] = cache_stats.compressed_bytes
    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Precompute terrain v2 tile cache.")
    parser.add_argument("--layer", default="hand")
    parser.add_argument("--region-id", default="birmingham-prototype")
    parser.add_argument("--min-zoom", type=int, default=9)
    parser.add_argument("--max-zoom", type=int, default=12)
    parser.add_argument("--cache-dir", type=Path, default=TERRAIN_TILE_CACHE_DIR)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-empty",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip source-covered tiles that render to all NODATA.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stats = precompute_region(args)
    if args.json:
        print(json.dumps(stats, indent=2, sort_keys=True))
        return

    print("Terrain cache precompute")
    print(f"  layer/version: {stats['layer']} / {stats['dataset_version']}")
    print(f"  region: {stats['region_id']}")
    print(f"  candidate tiles: {stats['candidate_tiles']}")
    print(
        f"  written/existing/skipped-empty: {stats['written']} / {stats['existing']} / {stats['empty_skipped']}"
    )
    print(f"  written compressed bytes: {format_bytes(int(stats['compressed_bytes']))}")
    print(
        f"  cache total: {stats['cache_tiles_total']} tiles, {format_bytes(int(stats['cache_bytes_total']))}"
    )
    print(f"  max render: {float(stats['max_render_ms']):.1f} ms")


if __name__ == "__main__":
    main()
