#!/usr/bin/env python3
"""WhiteboxTools HAND-style HUC unit benchmark."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import rasterio.features
import rasterio.transform

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.hand.huc_boundary_gate import (  # noqa: E402
    DEFAULT_BOUNDARY_BUFFER_KM,
    estimate_buffered_shape,
    format_bytes,
    project_geometry,
    source_cog_path,
)
from tools.hand.huc_scale_gate import (  # noqa: E402
    DEFAULT_DEM_RESOLUTION_M,
    DEFAULT_MAX_RSS_MB,
    DEFAULT_MAX_SOURCE_COG_BYTES,
    DEFAULT_MAX_WALL_S,
)
from tools.hand.huc_unit_gate import (  # noqa: E402
    DEFAULT_HUC,
    DEFAULT_HUC_LEVEL,
    DEFAULT_SAMPLE_COUNT,
    diff_against_reference,
    fetch_huc_unit,
    unit_region_id,
)
from tools.prototypes import generate_birmingham_drainage as hand_gen  # noqa: E402

NODATA_FLOAT = -9999.0


def whitebox_region_id(unit, buffer_km: float) -> str:
    return f"{unit_region_id(unit, buffer_km)}-whitebox-eas"


def write_dem(
    path: Path, dem: np.ndarray, x: np.ndarray, y: np.ndarray, crs: str
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    valid = np.isfinite(dem)
    values = np.where(valid, dem, NODATA_FLOAT).astype(np.float32)
    profile = {
        "driver": "GTiff",
        "height": values.shape[0],
        "width": values.shape[1],
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": hand_gen.raster_transform(x, y),
        "nodata": NODATA_FLOAT,
        "compress": "DEFLATE",
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(values, 1)


def write_streams(
    path: Path,
    *,
    dem_shape: tuple[int, int],
    transform,
    flowlines,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    stream_shapes = [
        (geom, 1)
        for geom in flowlines.geometry
        if geom is not None and not geom.is_empty
    ]
    streams = rasterio.features.rasterize(
        stream_shapes,
        out_shape=dem_shape,
        transform=transform,
        fill=0,
        dtype="uint8",
        all_touched=True,
    )
    stream_count = int(np.count_nonzero(streams))
    if stream_count == 0:
        raise RuntimeError("No Whitebox stream cells were rasterized.")
    profile = {
        "driver": "GTiff",
        "height": streams.shape[0],
        "width": streams.shape[1],
        "count": 1,
        "dtype": "uint8",
        "crs": flowlines.crs,
        "transform": transform,
        "nodata": 0,
        "compress": "DEFLATE",
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(streams, 1)
    return stream_count


def run_whitebox_elevation_above_stream(
    *, dem_path: Path, streams_path: Path, output_path: Path
) -> None:
    import whitebox

    wbt = whitebox.WhiteboxTools()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    code = wbt.run_tool(
        "ElevationAboveStream",
        [
            f"--dem={dem_path}",
            f"--streams={streams_path}",
            f"--output={output_path}",
        ],
    )
    if code != 0:
        raise RuntimeError(f"Whitebox ElevationAboveStream failed with exit {code}")


def write_clipped_source_cog(
    *,
    whitebox_output: Path,
    source_cog: Path,
    geometry_wgs84,
) -> dict[str, Any]:
    with rasterio.open(whitebox_output) as src:
        values = src.read(1).astype(np.float32)
        transform = src.transform
        crs = str(src.crs)
        nodata = src.nodata
    geometry = project_geometry(geometry_wgs84, source_crs="EPSG:4326", target_crs=crs)
    polygon_mask = rasterio.features.geometry_mask(
        [geometry],
        out_shape=values.shape,
        transform=transform,
        invert=True,
        all_touched=True,
    )
    valid = polygon_mask & np.isfinite(values) & (values >= 0)
    if nodata is not None:
        valid &= values != nodata
    hand = np.where(valid, values, np.nan).astype(np.float32)
    rows, cols = np.where(polygon_mask)
    if len(rows) == 0 or len(cols) == 0:
        raise RuntimeError("Whitebox output did not overlap the HUC polygon footprint.")
    row_slice = slice(int(rows.min()), int(rows.max()) + 1)
    col_slice = slice(int(cols.min()), int(cols.max()) + 1)
    clipped = hand[row_slice, col_slice]
    source_cog.parent.mkdir(parents=True, exist_ok=True)
    height, width = values.shape
    x, _ = rasterio.transform.xy(
        transform,
        np.zeros(width, dtype=np.int64),
        np.arange(width, dtype=np.int64),
        offset="center",
    )
    _, y = rasterio.transform.xy(
        transform,
        np.arange(height, dtype=np.int64),
        np.zeros(height, dtype=np.int64),
        offset="center",
    )
    hand_gen.write_source_cog(
        clipped,
        np.asarray(x[col_slice], dtype=np.float64),
        np.asarray(y[row_slice], dtype=np.float64),
        crs,
    )
    valid_count = int(np.count_nonzero(np.isfinite(clipped) & (clipped >= 0)))
    valid_values = clipped[np.isfinite(clipped) & (clipped >= 0)]
    if valid_values.size == 0:
        raise RuntimeError(
            "Whitebox output had no valid HAND cells inside the HUC polygon."
        )
    threshold_stats = {}
    for feet in (3, 6, 10):
        meters = feet * 0.3048
        threshold_stats[f"{feet}ft"] = {
            "cells": int(np.count_nonzero(valid_values <= meters)),
            "percent": round(
                float(
                    np.count_nonzero(valid_values <= meters) * 100.0 / valid_values.size
                ),
                2,
            ),
        }
    return {
        "whitebox_nodata": None if nodata is None else float(nodata),
        "polygon_cells": int(clipped.size),
        "valid_cells": valid_count,
        "nodata_cells": int(clipped.size - valid_count),
        "valid_cell_pct": round(float(valid_count * 100.0 / clipped.size), 2),
        "threshold_stats_ft": threshold_stats,
        "hand_min_m": round(float(np.min(valid_values)), 3),
        "hand_p50_m": round(float(np.percentile(valid_values, 50)), 3),
        "hand_p95_m": round(float(np.percentile(valid_values, 95)), 3),
        "hand_p99_m": round(float(np.percentile(valid_values, 99)), 3),
    }


def run_whitebox_unit(
    *,
    level: int,
    code: str,
    buffer_km: float,
    data_root: Path,
    artifact_root: Path,
    report_root: Path,
    dem_resolution_m: int,
    reference_cog: Path | None,
    sample_count: int,
    seed: int,
) -> dict[str, Any]:
    unit, geometry_wgs84 = fetch_huc_unit(level, code)
    estimate = estimate_buffered_shape(
        geometry_wgs84, buffer_km=buffer_km, resolution_m=dem_resolution_m
    )
    region_id = whitebox_region_id(unit, buffer_km)
    artifact_dir = artifact_root / "hand-whitebox" / region_id
    source_cog = source_cog_path(data_root, region_id)
    hand_gen.configure_runtime(
        hand_gen.PrototypeConfig(
            name=region_id,
            title=f"{unit.name} Whitebox HAND",
            bbox_lonlat=estimate.compute_bbox_lonlat,
            dem_resolution_m=dem_resolution_m,
            stream_min_order=2,
            stream_burn_depth_m=0.0,
            flow_accumulation_drain_threshold_km2=0.0,
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
    transform = hand_gen.raster_transform(x, y)
    dem_path = artifact_dir / "input-dem.tif"
    streams_path = artifact_dir / "input-streams.tif"
    output_path = artifact_dir / "whitebox-elevation-above-stream.tif"
    write_dem(dem_path, dem, x, y, crs)
    stream_cells = write_streams(
        streams_path, dem_shape=dem.shape, transform=transform, flowlines=flowlines
    )
    run_whitebox_elevation_above_stream(
        dem_path=dem_path, streams_path=streams_path, output_path=output_path
    )
    raster_stats = write_clipped_source_cog(
        whitebox_output=output_path,
        source_cog=source_cog,
        geometry_wgs84=geometry_wgs84,
    )
    build = {
        "wall_time_s": round(time.perf_counter() - started, 2),
        "peak_rss_mb": round(hand_gen.peak_rss_mb(), 1),
        "source_cog_bytes": source_cog.stat().st_size,
    }
    result = {
        "unit": asdict(unit),
        "region_id": region_id,
        "source_cog": str(source_cog),
        "artifact_dir": str(artifact_dir),
        "params": {
            "buffer_km": buffer_km,
            "dem_resolution_m": dem_resolution_m,
            "engine": "WhiteboxTools ElevationAboveStream",
        },
        "estimate": {
            "compute_bbox": asdict(estimate.compute_bbox),
            "output_bbox": asdict(estimate.output_bbox),
            "compute_bbox_lonlat": estimate.compute_bbox_lonlat,
            "output_bbox_lonlat": estimate.output_bbox_lonlat,
        },
        "build": build,
        "raster": raster_stats,
        "streams": {
            "selected_flowline_count": int(len(flowlines)),
            "stream_cells": stream_cells,
        },
        "checks": {
            "wall_time": build["wall_time_s"] <= DEFAULT_MAX_WALL_S,
            "peak_rss": build["peak_rss_mb"] <= DEFAULT_MAX_RSS_MB,
            "source_cog_size": build["source_cog_bytes"]
            <= DEFAULT_MAX_SOURCE_COG_BYTES,
        },
    }
    write_report(report_root, result)
    if reference_cog is not None:
        diff_result = diff_against_reference(
            reference_cog=reference_cog,
            candidate_cog=source_cog,
            report_root=report_root,
            region_id=region_id,
            sample_count=sample_count,
            seed=seed,
        )
        write_correctness_checks(report_root, region_id, diff_result)
    return result


def write_correctness_checks(
    report_root: Path, region_id: str, diff_result: dict[str, Any]
) -> dict[str, Any]:
    abs_diff = diff_result["abs_diff_m"]
    thresholds = diff_result["thresholds"]
    checks = {
        "p99_abs_diff_lte_1m": (abs_diff["p99"] is not None and abs_diff["p99"] <= 1.0),
        "within_1m_pct_gte_99": (
            abs_diff["within_1m_pct"] is not None and abs_diff["within_1m_pct"] >= 99.0
        ),
        "jaccard_3ft_gte_0_97": (
            thresholds["3ft"]["jaccard"] is not None
            and thresholds["3ft"]["jaccard"] >= 0.97
        ),
        "jaccard_6ft_gte_0_97": (
            thresholds["6ft"]["jaccard"] is not None
            and thresholds["6ft"]["jaccard"] >= 0.97
        ),
        "jaccard_10ft_gte_0_97": (
            thresholds["10ft"]["jaccard"] is not None
            and thresholds["10ft"]["jaccard"] >= 0.97
        ),
    }
    decision = {
        "gate": "whitebox-huc8-smoke",
        "passes_gate_8_correctness": all(checks.values()),
        "checks": checks,
        "caveat": (
            "This compares a mapped-flowline Whitebox stream raster against the "
            "pyflwdir HUC4 reference. A pass is not production acceptance until "
            "the drainage definition and DEM conditioning are comparable."
        ),
    }
    report_dir = report_root / region_id
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "correctness-checks.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        "# Whitebox Correctness Checks",
        "",
        f"- Gate 8 correctness pass: `{decision['passes_gate_8_correctness']}`.",
        f"- p99 <= 1m: `{checks['p99_abs_diff_lte_1m']}`.",
        f"- >=99% within 1m: `{checks['within_1m_pct_gte_99']}`.",
        f"- 3ft/6ft/10ft Jaccard >=0.97: `{checks['jaccard_3ft_gte_0_97']}` / `{checks['jaccard_6ft_gte_0_97']}` / `{checks['jaccard_10ft_gte_0_97']}`.",
        "",
        decision["caveat"],
    ]
    (report_dir / "correctness-summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return decision


def write_report(report_root: Path, result: dict[str, Any]) -> None:
    report_dir = report_root / result["region_id"]
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "metrics.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    build = result["build"]
    lines = [
        f"# Whitebox HAND Unit: HUC{result['unit']['level']} {result['unit']['code']} {result['unit']['name']}",
        "",
        f"- Output: `{result['source_cog']}`.",
        f"- Wall time: `{build['wall_time_s']}s` ({result['checks']['wall_time']}).",
        f"- Peak RSS: `{build['peak_rss_mb']} MB` ({result['checks']['peak_rss']}).",
        f"- Source COG: `{format_bytes(build['source_cog_bytes'])}` ({result['checks']['source_cog_size']}).",
        f"- Selected flowlines: `{result['streams']['selected_flowline_count']}`; stream cells: `{result['streams']['stream_cells']}`.",
        f"- Valid cells: `{result['raster']['valid_cells']}` of `{result['raster']['polygon_cells']}` (`{result['raster']['valid_cell_pct']}%`).",
        f"- 3ft/6ft/10ft area: `{result['raster']['threshold_stats_ft']['3ft']['percent']}%` / `{result['raster']['threshold_stats_ft']['6ft']['percent']}%` / `{result['raster']['threshold_stats_ft']['10ft']['percent']}%`.",
        f"- p50/p95/p99 HAND: `{result['raster']['hand_p50_m']}` / `{result['raster']['hand_p95_m']}` / `{result['raster']['hand_p99_m']}` m.",
        "",
        "Caveat: this is a native-engine smoke rejector, not a production acceptance test. It uses a rasterized mapped-flowline stream mask and raw DEM routing, so a pass would still need drainage-definition and conditioning parity before CONUS batching.",
    ]
    (report_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--huc-level", type=int, default=DEFAULT_HUC_LEVEL)
    parser.add_argument("--huc", default=DEFAULT_HUC)
    parser.add_argument("--buffer-km", type=float, default=DEFAULT_BOUNDARY_BUFFER_KM)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("scratch"))
    parser.add_argument(
        "--report-root", type=Path, default=Path("docs/qa/hand-whitebox")
    )
    parser.add_argument(
        "--dem-resolution-m", type=int, default=DEFAULT_DEM_RESOLUTION_M
    )
    parser.add_argument("--reference-cog", type=Path)
    parser.add_argument("--sample-count", type=int, default=DEFAULT_SAMPLE_COUNT)
    parser.add_argument("--seed", type=int, default=17)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_whitebox_unit(
        level=args.huc_level,
        code=args.huc,
        buffer_km=args.buffer_km,
        data_root=args.data_root,
        artifact_root=args.artifact_root,
        report_root=args.report_root,
        dem_resolution_m=args.dem_resolution_m,
        reference_cog=args.reference_cog,
        sample_count=args.sample_count,
        seed=args.seed,
    )
    print(json.dumps(result["build"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
