#!/usr/bin/env python3
"""Run and report the HUC4-scale HAND compute gate."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.prototypes import generate_birmingham_drainage as hand_gen  # noqa: E402

DEFAULT_HUC4 = "0312"
DEFAULT_DEM_RESOLUTION_M = 10
DEFAULT_STREAM_BURN_DEPTH_M = 5.0
DEFAULT_ACCUMULATION_THRESHOLD_KM2 = 16.0
DEFAULT_MAX_WALL_S = 3 * 60 * 60
DEFAULT_MAX_RSS_MB = 24 * 1024
DEFAULT_MAX_SOURCE_COG_BYTES = 500 * 1000 * 1000


@dataclass(frozen=True)
class Huc4Region:
    huc4: str
    name: str
    states: str
    area_km2: float
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class BBoxEstimate:
    width_m: float
    height_m: float
    columns: int
    rows: int
    cells: int
    raw_u16_bytes: int


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "region"


def format_bytes(byte_count: int | float) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(byte_count)
    for unit in units:
        if value < 1000 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1000
    return f"{value:.1f} TB"


def fetch_huc4(huc4: str) -> Huc4Region:
    from pygeohydro import WBD

    wbd = WBD("huc4", outfields=["huc4", "name", "areasqkm", "states"])
    gdf = wbd.byids("huc4", [huc4])
    if len(gdf) != 1:
        raise RuntimeError(f"Expected one WBD HUC4 row for {huc4}, got {len(gdf)}")
    row = gdf.iloc[0]
    return Huc4Region(
        huc4=str(row["huc4"]),
        name=str(row["name"]),
        states=str(row["states"]),
        area_km2=float(row["areasqkm"]),
        bbox=tuple(float(value) for value in row.geometry.bounds),
    )


def estimate_projected_bbox(
    bbox: tuple[float, float, float, float],
    *,
    resolution_m: int,
    crs: str = "EPSG:5070",
) -> BBoxEstimate:
    from pyproj import Transformer

    west, south, east, north = bbox
    lon = [west, west, east, east]
    lat = [south, north, south, north]
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    x, y = transformer.transform(lon, lat)
    width_m = float(max(x) - min(x))
    height_m = float(max(y) - min(y))
    columns = max(1, round(width_m / resolution_m))
    rows = max(1, round(height_m / resolution_m))
    cells = columns * rows
    return BBoxEstimate(
        width_m=width_m,
        height_m=height_m,
        columns=columns,
        rows=rows,
        cells=cells,
        raw_u16_bytes=cells * 2,
    )


def source_cog_path(data_root: Path, region_id: str) -> Path:
    return data_root / "terrain" / "hand" / f"{region_id}.tif"


def run_generator(
    *,
    region: Huc4Region,
    region_id: str,
    artifact_dir: Path,
    source_cog: Path,
    dem_resolution_m: int,
    stream_burn_depth_m: float,
    accumulation_threshold_km2: float,
    write_static_tiles: bool,
) -> dict[str, Any]:
    hand_gen.configure_runtime(
        hand_gen.PrototypeConfig(
            name=region_id,
            title=f"{region.name} HUC4 HAND Gate",
            bbox_lonlat=region.bbox,
            dem_resolution_m=dem_resolution_m,
            stream_min_order=2,
            stream_burn_depth_m=stream_burn_depth_m,
            flow_accumulation_drain_threshold_km2=accumulation_threshold_km2,
            zoom_min=9,
            zoom_max=12,
        ),
        output_dir=artifact_dir,
        source_cog=source_cog,
    )

    started = time.perf_counter()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    dem, x, y, crs = hand_gen.fetch_dem()
    flowlines = hand_gen.fetch_flowlines(crs)
    hand, upstream_area_km2, drain_mask, stream_mask = hand_gen.derive_drainage_height(
        dem, x, y, flowlines
    )
    tile_counts = hand_gen.write_tiles(hand, x, y, crs) if write_static_tiles else {}
    hand_gen.write_source_cog(hand, x, y, crs)
    hand_gen.make_preview(hand, drain_mask, stream_mask)
    build_metrics = {
        "wall_time_s": round(time.perf_counter() - started, 2),
        "peak_rss_mb": round(hand_gen.peak_rss_mb(), 1),
        "source_cog_bytes": hand_gen.SOURCE_COG_PATH.stat().st_size,
    }
    hand_gen.write_metadata(
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
        build_metrics,
    )
    return json.loads(hand_gen.META_PATH.read_text(encoding="utf-8"))


def build_gate_result(
    *,
    metadata: dict[str, Any],
    max_wall_s: int,
    max_rss_mb: int,
    max_source_cog_bytes: int,
) -> dict[str, Any]:
    build = metadata["build"]
    valid_cells = int(metadata["valid_hand_cells"])
    nodata_cells = int(metadata["nodata_cells"])
    total_cells = valid_cells + nodata_cells
    valid_cell_pct = valid_cells * 100.0 / total_cells if total_cells else 0.0
    threshold_3ft = metadata["threshold_stats_ft"]["3"]
    checks = {
        "wall_time": float(build["wall_time_s"]) <= max_wall_s,
        "peak_rss": float(build["peak_rss_mb"]) <= max_rss_mb,
        "source_cog_size": int(build["source_cog_bytes"]) <= max_source_cog_bytes,
    }
    return {
        "checks": checks,
        "automated_pass": all(checks.values()),
        "valid_cell_pct": round(valid_cell_pct, 2),
        "area_3ft_pct": threshold_3ft["percent"],
        "wall_time_s": build["wall_time_s"],
        "peak_rss_mb": build["peak_rss_mb"],
        "source_cog_bytes": build["source_cog_bytes"],
    }


def write_report(
    *,
    report_dir: Path,
    region: Huc4Region,
    region_id: str,
    bbox_estimate: BBoxEstimate,
    metadata: dict[str, Any],
    gate_result: dict[str, Any],
    artifact_dir: Path,
    source_cog: Path,
    thresholds: dict[str, int],
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    preview_src = artifact_dir / "preview.png"
    preview_dst = report_dir / "preview.png"
    if preview_src.exists():
        shutil.copyfile(preview_src, preview_dst)

    metrics = {
        "region": asdict(region),
        "region_id": region_id,
        "bbox_estimate": asdict(bbox_estimate),
        "params": {
            "dem_resolution_m": metadata["dem_resolution_m"],
            "stream_burn_depth_m": metadata["routing"]["stream_burn_depth_m"],
            "accumulation_threshold_km2": metadata["routing"][
                "accumulation_drain_threshold_km2"
            ],
        },
        "thresholds": thresholds,
        "gate_result": gate_result,
        "source_cog": str(source_cog),
        "artifact_dir": str(artifact_dir),
        "generator_metadata": metadata,
    }
    (report_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    status = "PASS" if gate_result["automated_pass"] else "FAIL"
    checks = gate_result["checks"]
    lines = [
        f"# HUC-Scale HAND Gate: {region.huc4} {region.name}",
        "",
        f"- Automated result: **{status}**.",
        "- Visual boundary-artifact review: pending until the generated preview is inspected.",
        f"- Region states: `{region.states}`.",
        f"- WBD area: `{region.area_km2:,.2f} km^2`.",
        f"- Bbox: `{region.bbox}`.",
        f"- DEM resolution: `{metadata['dem_resolution_m']}m`.",
        f"- Drain params: burn `{metadata['routing']['stream_burn_depth_m']}m`, accumulation `{metadata['routing']['accumulation_drain_threshold_km2']} km^2`.",
        f"- Source COG: `{source_cog}`.",
        f"- Scratch artifacts: `{artifact_dir}`.",
        "",
        "## Measured Gate Metrics",
        "",
        "| Metric | Value | Threshold | Pass |",
        "|---|---:|---:|---:|",
        f"| Wall time | {gate_result['wall_time_s']}s | {thresholds['max_wall_s']}s | {checks['wall_time']} |",
        f"| Peak RSS | {gate_result['peak_rss_mb']} MB | {thresholds['max_rss_mb']} MB | {checks['peak_rss']} |",
        f"| Source COG | {format_bytes(gate_result['source_cog_bytes'])} | {format_bytes(thresholds['max_source_cog_bytes'])} | {checks['source_cog_size']} |",
        f"| Valid HAND cells | {gate_result['valid_cell_pct']}% | report-only | n/a |",
        f"| 3ft area | {gate_result['area_3ft_pct']}% | report-only | n/a |",
        "",
        "## Pre-Run Size Estimate",
        "",
        f"- Projected bbox grid: `{bbox_estimate.columns:,} x {bbox_estimate.rows:,}` cells.",
        f"- Bbox cells: `{bbox_estimate.cells:,}`.",
        f"- Raw uint16 bbox bytes: `{format_bytes(bbox_estimate.raw_u16_bytes)}` before compression and overviews.",
        "",
        "## Interpretation",
        "",
        "- This gate measures the current bbox-based prototype path. It does not prove that large HUC4s can run without regional tiling.",
        "- A pass means one small real HUC4 can fit the current approach. A fail means the CONUS path must be tiled before any national batch.",
    ]
    (report_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--huc4", default=DEFAULT_HUC4)
    parser.add_argument(
        "--dem-resolution-m", type=int, default=DEFAULT_DEM_RESOLUTION_M
    )
    parser.add_argument(
        "--stream-burn-depth-m", type=float, default=DEFAULT_STREAM_BURN_DEPTH_M
    )
    parser.add_argument(
        "--flow-accumulation-drain-threshold-km2",
        type=float,
        default=DEFAULT_ACCUMULATION_THRESHOLD_KM2,
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(os.getenv("FLOODMAP_DATA_ROOT", "data")),
    )
    parser.add_argument("--artifact-root", type=Path, default=Path("scratch"))
    parser.add_argument(
        "--report-root", type=Path, default=Path("docs/qa/hand-huc-scale")
    )
    parser.add_argument("--max-wall-s", type=int, default=DEFAULT_MAX_WALL_S)
    parser.add_argument("--max-rss-mb", type=int, default=DEFAULT_MAX_RSS_MB)
    parser.add_argument(
        "--max-source-cog-bytes", type=int, default=DEFAULT_MAX_SOURCE_COG_BYTES
    )
    parser.add_argument("--write-static-tiles", action="store_true")
    parser.add_argument("--estimate-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    region = fetch_huc4(args.huc4)
    region_id = f"huc4-{region.huc4}-{slugify(region.name)}"
    bbox_estimate = estimate_projected_bbox(
        region.bbox, resolution_m=args.dem_resolution_m
    )
    report_dir = args.report_root / region_id
    artifact_dir = args.artifact_root / "hand-huc-scale" / region_id
    cog_path = source_cog_path(args.data_root, region_id)

    if args.estimate_only:
        print(
            json.dumps(
                {
                    "region": asdict(region),
                    "region_id": region_id,
                    "bbox_estimate": asdict(bbox_estimate),
                    "source_cog": str(cog_path),
                    "artifact_dir": str(artifact_dir),
                    "report_dir": str(report_dir),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    metadata = run_generator(
        region=region,
        region_id=region_id,
        artifact_dir=artifact_dir,
        source_cog=cog_path,
        dem_resolution_m=args.dem_resolution_m,
        stream_burn_depth_m=args.stream_burn_depth_m,
        accumulation_threshold_km2=args.flow_accumulation_drain_threshold_km2,
        write_static_tiles=args.write_static_tiles,
    )
    thresholds = {
        "max_wall_s": args.max_wall_s,
        "max_rss_mb": args.max_rss_mb,
        "max_source_cog_bytes": args.max_source_cog_bytes,
    }
    gate_result = build_gate_result(
        metadata=metadata,
        max_wall_s=args.max_wall_s,
        max_rss_mb=args.max_rss_mb,
        max_source_cog_bytes=args.max_source_cog_bytes,
    )
    write_report(
        report_dir=report_dir,
        region=region,
        region_id=region_id,
        bbox_estimate=bbox_estimate,
        metadata=metadata,
        gate_result=gate_result,
        artifact_dir=artifact_dir,
        source_cog=cog_path,
        thresholds=thresholds,
    )
    print(json.dumps(gate_result, indent=2, sort_keys=True))
    print(f"Wrote {report_dir}")


if __name__ == "__main__":
    main()
