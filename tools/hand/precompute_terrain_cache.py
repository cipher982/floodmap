#!/usr/bin/env python3
"""Precompute v2 terrain cache tiles from a source COG manifest region."""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from terrain import U16_NODATA, lonlat_to_tile_pixel  # noqa: E402
from terrain_cache import TerrainTileCache  # noqa: E402
from terrain_cog import clear_cog_tile_cache, render_cog_tile_with_cache  # noqa: E402


def iter_tiles_for_bbox(
    bbox: tuple[float, float, float, float], min_zoom: int, max_zoom: int
) -> list[tuple[int, int, int]]:
    west, south, east, north = bbox
    tiles: list[tuple[int, int, int]] = []
    for z in range(min_zoom, max_zoom + 1):
        x0, y_top, _, _ = lonlat_to_tile_pixel(west, north, z)
        x1, y_bottom, _, _ = lonlat_to_tile_pixel(east, south, z)
        max_coord = (2**z) - 1
        for x in range(max(0, x0), min(max_coord, x1) + 1):
            for y in range(max(0, y_top), min(max_coord, y_bottom) + 1):
                tiles.append((z, x, y))
    return tiles


def filter_tiles_by_shard(
    tiles: list[tuple[int, int, int]], shard_index: int, shard_count: int
) -> list[tuple[int, int, int]]:
    if shard_count < 1:
        raise ValueError("shard_count must be >= 1")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError("shard_index must satisfy 0 <= shard_index < shard_count")
    if shard_count == 1:
        return tiles
    return [
        tile for tile in tiles if tile_shard_index(tile, shard_count) == shard_index
    ]


def tile_shard_index(tile: tuple[int, int, int], shard_count: int) -> int:
    z, x, y = tile
    return ((z * 73_856_093) ^ (x * 19_349_663) ^ (y * 83_492_791)) % shard_count


def process_tile(
    *,
    cache: TerrainTileCache,
    args: argparse.Namespace,
    dataset_version: str,
    source_path: Path | None,
    tile: tuple[int, int, int],
) -> dict[str, int | float | str | bool]:
    z, x, y = tile
    path = cache.br_path(args.layer, dataset_version, z, x, y)
    existed = path.exists()
    if existed and not args.overwrite:
        return {"status": "existing"}

    if args.dry_run:
        return {"status": "dry-run", "existing": existed}

    if source_path is None:
        raise RuntimeError("source path unexpectedly absent outside dry-run")
    payload, _, elapsed_ms = render_cog_tile_with_cache(source_path, z, x, y)
    values = np.frombuffer(payload, dtype=np.uint16)
    data_status = "source-nodata" if np.all(values == U16_NODATA) else "ok"
    if args.skip_empty and data_status == "source-nodata":
        return {
            "status": "empty-skipped",
            "pre_existing": existed,
            "elapsed_ms": elapsed_ms,
        }

    written_path = cache.write_tile(
        args.layer,
        dataset_version,
        z,
        x,
        y,
        payload,
        data_status,
    )
    return {
        "status": "written",
        "pre_existing": existed,
        "compressed_bytes": written_path.stat().st_size,
        "elapsed_ms": elapsed_ms,
    }


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
    all_tiles = iter_tiles_for_bbox(region.bbox, args.min_zoom, args.max_zoom)
    tiles = filter_tiles_by_shard(all_tiles, args.shard_index, args.shard_count)
    if args.limit:
        tiles = tiles[: args.limit]

    clear_cog_tile_cache()
    stats: dict[str, int | str | float] = {
        "layer": args.layer,
        "dataset_version": manifest.dataset_version,
        "region_id": region.id,
        "source": region.url if source_path is None else str(source_path),
        "cache_dir": str(args.cache_dir),
        "total_tiles": len(all_tiles),
        "candidate_tiles": len(tiles),
        "workers": args.workers,
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "written": 0,
        "existing": 0,
        "empty_skipped": 0,
        "compressed_bytes": 0,
        "max_render_ms": 0.0,
    }

    def record_result(result: dict[str, int | float | str | bool]) -> None:
        if result["status"] == "existing":
            stats["existing"] = int(stats["existing"]) + 1
        if result["status"] == "written":
            stats["written"] = int(stats["written"]) + 1
            stats["compressed_bytes"] = int(stats["compressed_bytes"]) + int(
                result["compressed_bytes"]
            )
        elif result["status"] == "empty-skipped":
            stats["empty_skipped"] = int(stats["empty_skipped"]) + 1
        if "elapsed_ms" in result:
            stats["max_render_ms"] = max(
                float(stats["max_render_ms"]), float(result["elapsed_ms"])
            )

    if args.workers == 1 or args.dry_run:
        for tile in tiles:
            record_result(
                process_tile(
                    cache=cache,
                    args=args,
                    dataset_version=manifest.dataset_version,
                    source_path=source_path,
                    tile=tile,
                )
            )
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            submitted = [
                executor.submit(
                    process_tile,
                    cache=cache,
                    args=args,
                    dataset_version=manifest.dataset_version,
                    source_path=source_path,
                    tile=tile,
                )
                for tile in tiles
            ]
            for completed in as_completed(submitted):
                record_result(completed.result())

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
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument(
        "--skip-empty",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip source-covered tiles that render to all NODATA.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be >= 1")
    if args.shard_count < 1:
        parser.error("--shard-count must be >= 1")
    if args.shard_index < 0 or args.shard_index >= args.shard_count:
        parser.error("--shard-index must satisfy 0 <= index < shard-count")
    return args


def main() -> None:
    args = parse_args()
    stats = precompute_region(args)
    if args.json:
        print(json.dumps(stats, indent=2, sort_keys=True))
        return

    print("Terrain cache precompute")
    print(f"  layer/version: {stats['layer']} / {stats['dataset_version']}")
    print(f"  region: {stats['region_id']}")
    print(
        f"  candidate tiles: {stats['candidate_tiles']} of {stats['total_tiles']} "
        f"(shard {stats['shard_index']}/{stats['shard_count']}, workers {stats['workers']})"
    )
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
