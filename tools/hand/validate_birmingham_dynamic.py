#!/usr/bin/env python3
"""Compare Birmingham dynamic COG rendering against committed prototype tiles."""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "api"))

from terrain import TILE_SIZE, U16_NODATA, lonlat_to_tile_pixel  # noqa: E402
from terrain_cog import (  # noqa: E402
    clear_cog_tile_cache,
    render_cog_tile_with_cache,
    sample_cog_point,
)

DATA_ROOT = Path(os.getenv("FLOODMAP_DATA_ROOT", ROOT / "data")).expanduser()
DEFAULT_COG = DATA_ROOT / "terrain" / "hand" / "birmingham-drainage.tif"
DEFAULT_STATIC_TILES = (
    ROOT / "src" / "web" / "prototypes" / "birmingham-drainage" / "tiles"
)
SAMPLE_LAT = 33.5207
SAMPLE_LON = -86.8025
DECIMETER_TO_FOOT = 0.328084


def parse_tile_path(tile_path: Path, root: Path) -> tuple[int, int, int]:
    rel = tile_path.relative_to(root)
    z = int(rel.parts[0])
    x = int(rel.parts[1])
    y = int(rel.parts[2].removesuffix(".u16"))
    return z, x, y


def percentile(values: np.ndarray, pct: float) -> float:
    if values.size == 0:
        return 0.0
    return float(np.percentile(values, pct))


def static_sample(static_tiles: Path) -> int | None:
    tile_x, tile_y, pixel_x, pixel_y = lonlat_to_tile_pixel(
        SAMPLE_LON, SAMPLE_LAT, zoom=12
    )
    tile_path = static_tiles / "12" / str(tile_x) / f"{tile_y}.u16"
    if not tile_path.exists():
        return None
    values = np.frombuffer(tile_path.read_bytes(), dtype=np.uint16).reshape(
        TILE_SIZE, TILE_SIZE
    )
    value = int(values[pixel_y, pixel_x])
    return None if value == int(U16_NODATA) else value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cog", type=Path, default=DEFAULT_COG)
    parser.add_argument("--static-tiles", type=Path, default=DEFAULT_STATIC_TILES)
    parser.add_argument("--max-p95-ft", type=float, default=1.0)
    parser.add_argument("--max-nodata-mismatch-rate", type=float, default=0.005)
    args = parser.parse_args()

    if not args.cog.exists():
        raise SystemExit(f"Missing dynamic COG: {args.cog}")
    if not args.static_tiles.exists():
        raise SystemExit(f"Missing static tiles: {args.static_tiles}")

    tile_paths = sorted(args.static_tiles.glob("*/*/*.u16"))
    if not tile_paths:
        raise SystemExit(f"No static .u16 tiles found under {args.static_tiles}")

    clear_cog_tile_cache()
    all_diffs_ft: list[np.ndarray] = []
    cold_latencies: list[float] = []
    hot_latencies: list[float] = []
    by_zoom: dict[int, dict[str, float]] = defaultdict(
        lambda: {"tiles": 0, "valid": 0, "nodata_mismatch": 0, "total": 0}
    )

    for tile_path in tile_paths:
        z, x, y = parse_tile_path(tile_path, args.static_tiles)
        dynamic_payload, _, cold_ms = render_cog_tile_with_cache(args.cog, z, x, y)
        _, _, hot_ms = render_cog_tile_with_cache(args.cog, z, x, y)
        cold_latencies.append(cold_ms)
        hot_latencies.append(hot_ms)

        static = np.frombuffer(tile_path.read_bytes(), dtype=np.uint16)
        dynamic = np.frombuffer(dynamic_payload, dtype=np.uint16)
        valid_static = static != U16_NODATA
        valid_dynamic = dynamic != U16_NODATA
        valid_both = valid_static & valid_dynamic
        nodata_mismatch = valid_static ^ valid_dynamic
        diffs_ft = (
            np.abs(
                static[valid_both].astype(np.int32)
                - dynamic[valid_both].astype(np.int32)
            )
            * DECIMETER_TO_FOOT
        )
        if diffs_ft.size:
            all_diffs_ft.append(diffs_ft)

        zoom_stats = by_zoom[z]
        zoom_stats["tiles"] += 1
        zoom_stats["valid"] += int(valid_both.sum())
        zoom_stats["nodata_mismatch"] += int(nodata_mismatch.sum())
        zoom_stats["total"] += static.size

    diffs = np.concatenate(all_diffs_ft) if all_diffs_ft else np.array([], dtype=float)
    mismatch_count = sum(stats["nodata_mismatch"] for stats in by_zoom.values())
    total_pixels = sum(stats["total"] for stats in by_zoom.values())
    mismatch_rate = mismatch_count / total_pixels if total_pixels else 0.0

    static_value = static_sample(args.static_tiles)
    dynamic_value = sample_cog_point(args.cog, lon=SAMPLE_LON, lat=SAMPLE_LAT)

    print("Birmingham dynamic COG validation")
    print(f"  source COG: {args.cog}")
    print(f"  static tiles: {len(tile_paths)}")
    print(f"  valid comparison pixels: {diffs.size:,}")
    print(
        f"  abs diff p50/p95/max ft: {percentile(diffs, 50):.2f} / {percentile(diffs, 95):.2f} / {percentile(diffs, 100):.2f}"
    )
    print(
        f"  abs diff p99/p99.9 ft: {percentile(diffs, 99):.2f} / {percentile(diffs, 99.9):.2f}"
    )
    if diffs.size:
        over_10ft = int((diffs > 10).sum())
        print(f"  pixels over 10 ft diff: {over_10ft:,} ({over_10ft / diffs.size:.4%})")
    print(f"  nodata mismatch: {mismatch_count:,} pixels ({mismatch_rate:.4%})")
    print(
        f"  cold render p50/p95 ms: {statistics.median(cold_latencies):.1f} / {percentile(np.array(cold_latencies), 95):.1f}"
    )
    print(
        f"  hot render p50/p95 ms: {statistics.median(hot_latencies):.1f} / {percentile(np.array(hot_latencies), 95):.1f}"
    )
    print(
        "  sample downtown HAND ft static/dynamic: "
        f"{None if static_value is None else round(static_value * DECIMETER_TO_FOOT, 1)} / "
        f"{None if dynamic_value is None else round(dynamic_value * DECIMETER_TO_FOOT, 1)}"
    )

    for zoom in sorted(by_zoom):
        stats = by_zoom[zoom]
        zoom_mismatch = stats["nodata_mismatch"] / stats["total"]
        print(
            f"  z{zoom}: {int(stats['tiles'])} tiles, "
            f"{int(stats['valid']):,} valid px, nodata mismatch {zoom_mismatch:.4%}"
        )

    failed = False
    if percentile(diffs, 95) > args.max_p95_ft:
        print(
            f"FAIL: p95 diff exceeds {args.max_p95_ft:.2f} ft threshold",
            file=sys.stderr,
        )
        failed = True
    if mismatch_rate > args.max_nodata_mismatch_rate:
        print(
            "FAIL: nodata mismatch rate exceeds "
            f"{args.max_nodata_mismatch_rate:.4%} threshold",
            file=sys.stderr,
        )
        failed = True
    if static_value is None or dynamic_value is None:
        print("FAIL: downtown sample missing in one source", file=sys.stderr)
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
