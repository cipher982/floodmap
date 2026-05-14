#!/usr/bin/env python3
"""Build buffered, polygon-clipped HUC4 HAND outputs and seam QA."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import rasterio.features

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.hand.huc_scale_gate import (  # noqa: E402
    DEFAULT_ACCUMULATION_THRESHOLD_KM2,
    DEFAULT_DEM_RESOLUTION_M,
    DEFAULT_MAX_RSS_MB,
    DEFAULT_MAX_SOURCE_COG_BYTES,
    DEFAULT_MAX_WALL_S,
    DEFAULT_STREAM_BURN_DEPTH_M,
    BBoxEstimate,
    Huc4Region,
    build_gate_result,
    format_bytes,
    slugify,
)
from tools.prototypes import generate_birmingham_drainage as hand_gen  # noqa: E402

NODATA_U16 = 65535
DEFAULT_BOUNDARY_BUFFER_KM = 5.0
DEFAULT_BOUNDARY_PAIR = ("0106", "0107")
DEFAULT_SEAM_SAMPLE_SPACING_M = 100.0


@dataclass(frozen=True)
class Huc4Shape:
    region: Huc4Region
    geometry_wkt: str


@dataclass(frozen=True)
class BufferedEstimate:
    output_bbox: BBoxEstimate
    compute_bbox: BBoxEstimate
    output_bbox_lonlat: tuple[float, float, float, float]
    compute_bbox_lonlat: tuple[float, float, float, float]


def distance_tag(value: float) -> str:
    return f"{value:g}".replace(".", "p").replace("-", "m")


def boundary_region_id(region: Huc4Region, buffer_km: float) -> str:
    return f"huc4-{region.huc4}-{slugify(region.name)}-buffer{distance_tag(buffer_km)}km-clipped"


def pair_id(huc4_a: str, huc4_b: str, buffer_km: float) -> str:
    hucs = sorted([huc4_a, huc4_b])
    return f"pair-{'-'.join(hucs)}-buffer{distance_tag(buffer_km)}km"


def source_cog_path(data_root: Path, region_id: str) -> Path:
    return data_root / "terrain" / "hand" / f"{region_id}.tif"


def fetch_huc4_shape(huc4: str):
    from pygeohydro import WBD

    wbd = WBD("huc4", outfields=["huc4", "name", "areasqkm", "states"])
    gdf = wbd.byids("huc4", [huc4])
    if len(gdf) != 1:
        raise RuntimeError(f"Expected one WBD HUC4 row for {huc4}, got {len(gdf)}")
    row = gdf.iloc[0]
    region = Huc4Region(
        huc4=str(row["huc4"]),
        name=str(row["name"]),
        states=str(row["states"]),
        area_km2=float(row["areasqkm"]),
        bbox=tuple(float(value) for value in row.geometry.bounds),
    )
    return region, row.geometry


def project_geometry(geometry, *, source_crs: str, target_crs: str):
    import geopandas as gpd

    return gpd.GeoSeries([geometry], crs=source_crs).to_crs(target_crs).iloc[0]


def lonlat_bounds(geometry, *, source_crs: str) -> tuple[float, float, float, float]:
    import geopandas as gpd

    bounds = gpd.GeoSeries([geometry], crs=source_crs).to_crs("EPSG:4326").total_bounds
    return tuple(float(value) for value in bounds)


def projected_bounds_estimate(
    bounds: tuple[float, float, float, float], *, resolution_m: int
) -> BBoxEstimate:
    minx, miny, maxx, maxy = bounds
    width_m = float(maxx - minx)
    height_m = float(maxy - miny)
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


def estimate_buffered_shape(
    geometry_wgs84, *, buffer_km: float, resolution_m: int
) -> BufferedEstimate:
    output_geom = project_geometry(
        geometry_wgs84, source_crs="EPSG:4326", target_crs="EPSG:5070"
    )
    compute_geom = output_geom.buffer(buffer_km * 1000.0)
    return BufferedEstimate(
        output_bbox=projected_bounds_estimate(
            output_geom.bounds, resolution_m=resolution_m
        ),
        compute_bbox=projected_bounds_estimate(
            compute_geom.bounds, resolution_m=resolution_m
        ),
        output_bbox_lonlat=lonlat_bounds(output_geom, source_crs="EPSG:5070"),
        compute_bbox_lonlat=lonlat_bounds(compute_geom, source_crs="EPSG:5070"),
    )


def clip_to_polygon(
    *,
    dem: np.ndarray,
    hand: np.ndarray,
    upstream_area_km2: np.ndarray,
    drain_mask: np.ndarray,
    stream_mask: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    crs: str,
    geometry_wgs84,
) -> tuple[
    np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray
]:
    geometry = project_geometry(geometry_wgs84, source_crs="EPSG:4326", target_crs=crs)
    transform = hand_gen.raster_transform(x, y)
    polygon_mask = rasterio.features.geometry_mask(
        [geometry],
        out_shape=hand.shape,
        transform=transform,
        invert=True,
        all_touched=True,
    )
    rows, cols = np.where(polygon_mask)
    if len(rows) == 0 or len(cols) == 0:
        raise RuntimeError("HUC polygon did not overlap the computed DEM grid.")

    row_slice = slice(int(rows.min()), int(rows.max()) + 1)
    col_slice = slice(int(cols.min()), int(cols.max()) + 1)
    mask = polygon_mask[row_slice, col_slice]

    clipped_hand = np.where(mask, hand[row_slice, col_slice], np.nan).astype(np.float32)
    clipped_dem = np.where(mask, dem[row_slice, col_slice], np.nan).astype(np.float32)
    clipped_upstream = np.where(
        mask, upstream_area_km2[row_slice, col_slice], np.nan
    ).astype(np.float32)
    clipped_drain = drain_mask[row_slice, col_slice] & mask
    clipped_stream = stream_mask[row_slice, col_slice] & mask
    return (
        clipped_dem,
        clipped_hand,
        clipped_upstream,
        clipped_drain,
        clipped_stream,
        x[col_slice],
        y[row_slice],
    )


def intersecting_flowlines(flowlines, geometry_wgs84, crs: str):
    geometry = project_geometry(geometry_wgs84, source_crs="EPSG:4326", target_crs=crs)
    selected = flowlines[flowlines.intersects(geometry)].copy()
    return selected if not selected.empty else flowlines


def run_buffered_region(
    *,
    huc4: str,
    buffer_km: float,
    data_root: Path,
    artifact_root: Path,
    dem_resolution_m: int,
    stream_burn_depth_m: float,
    accumulation_threshold_km2: float,
) -> dict[str, Any]:
    region, geometry_wgs84 = fetch_huc4_shape(huc4)
    estimate = estimate_buffered_shape(
        geometry_wgs84, buffer_km=buffer_km, resolution_m=dem_resolution_m
    )
    region_id = boundary_region_id(region, buffer_km)
    artifact_dir = artifact_root / "hand-boundary" / region_id
    cog_path = source_cog_path(data_root, region_id)

    hand_gen.configure_runtime(
        hand_gen.PrototypeConfig(
            name=region_id,
            title=f"{region.name} Buffered HUC4 HAND",
            bbox_lonlat=estimate.compute_bbox_lonlat,
            dem_resolution_m=dem_resolution_m,
            stream_min_order=2,
            stream_burn_depth_m=stream_burn_depth_m,
            flow_accumulation_drain_threshold_km2=accumulation_threshold_km2,
            zoom_min=9,
            zoom_max=12,
        ),
        output_dir=artifact_dir,
        source_cog=cog_path,
    )

    started = time.perf_counter()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    dem, x, y, crs = hand_gen.fetch_dem()
    flowlines = hand_gen.fetch_flowlines(crs)
    hand, upstream_area_km2, drain_mask, stream_mask = hand_gen.derive_drainage_height(
        dem, x, y, flowlines
    )
    (
        clipped_dem,
        clipped_hand,
        clipped_upstream,
        clipped_drain,
        clipped_stream,
        clipped_x,
        clipped_y,
    ) = clip_to_polygon(
        dem=dem,
        hand=hand,
        upstream_area_km2=upstream_area_km2,
        drain_mask=drain_mask,
        stream_mask=stream_mask,
        x=x,
        y=y,
        crs=crs,
        geometry_wgs84=geometry_wgs84,
    )
    target_flowlines = intersecting_flowlines(flowlines, geometry_wgs84, crs)
    hand_gen.write_source_cog(clipped_hand, clipped_x, clipped_y, crs)
    hand_gen.make_preview(clipped_hand, clipped_drain, clipped_stream)
    build_metrics = {
        "wall_time_s": round(time.perf_counter() - started, 2),
        "peak_rss_mb": round(hand_gen.peak_rss_mb(), 1),
        "source_cog_bytes": hand_gen.SOURCE_COG_PATH.stat().st_size,
    }
    hand_gen.write_metadata(
        clipped_dem,
        clipped_hand,
        clipped_upstream,
        clipped_drain,
        clipped_stream,
        clipped_x,
        clipped_y,
        crs,
        target_flowlines,
        {},
        build_metrics,
    )

    metadata = json.loads(hand_gen.META_PATH.read_text(encoding="utf-8"))
    metadata["boundary_gate"] = {
        "buffer_km": buffer_km,
        "polygon_clipped": True,
        "compute_bbox_lonlat": list(estimate.compute_bbox_lonlat),
        "output_bbox_lonlat": list(estimate.output_bbox_lonlat),
        "compute_bbox_estimate": asdict(estimate.compute_bbox),
        "output_bbox_estimate": asdict(estimate.output_bbox),
    }
    hand_gen.META_PATH.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    result = {
        "region": asdict(region),
        "region_id": region_id,
        "buffer_km": buffer_km,
        "source_cog": str(cog_path),
        "artifact_dir": str(artifact_dir),
        "estimate": {
            "compute_bbox": asdict(estimate.compute_bbox),
            "output_bbox": asdict(estimate.output_bbox),
            "compute_bbox_lonlat": estimate.compute_bbox_lonlat,
            "output_bbox_lonlat": estimate.output_bbox_lonlat,
        },
        "metadata": metadata,
        "gate_result": build_gate_result(
            metadata=metadata,
            max_wall_s=DEFAULT_MAX_WALL_S,
            max_rss_mb=DEFAULT_MAX_RSS_MB,
            max_source_cog_bytes=DEFAULT_MAX_SOURCE_COG_BYTES,
        ),
    }
    (artifact_dir / "boundary-metrics.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def extract_lines(geometry):
    if geometry.is_empty:
        return []
    geom_type = geometry.geom_type
    if geom_type == "LineString":
        return [geometry]
    if geom_type == "MultiLineString":
        return list(geometry.geoms)
    if geom_type == "GeometryCollection":
        lines = []
        for part in geometry.geoms:
            lines.extend(extract_lines(part))
        return lines
    return []


def sample_line_points(lines: list[Any], spacing_m: float) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for line in lines:
        if line.length <= 0:
            continue
        count = max(2, int(line.length / spacing_m) + 1)
        for distance in np.linspace(0, line.length, count):
            point = line.interpolate(float(distance))
            points.append((float(point.x), float(point.y)))
    return points


def read_samples(path: Path, points: list[tuple[float, float]]) -> np.ndarray:
    with rasterio.open(path) as dataset:
        values = np.array(
            [value[0] for value in dataset.sample(points)], dtype=np.uint16
        )
    return values


def seam_metrics(
    *,
    huc4_a: str,
    huc4_b: str,
    cog_a: Path,
    cog_b: Path,
    spacing_m: float,
) -> dict[str, Any]:
    region_a, geom_a_wgs84 = fetch_huc4_shape(huc4_a)
    region_b, geom_b_wgs84 = fetch_huc4_shape(huc4_b)
    geom_a = project_geometry(
        geom_a_wgs84, source_crs="EPSG:4326", target_crs="EPSG:5070"
    )
    geom_b = project_geometry(
        geom_b_wgs84, source_crs="EPSG:4326", target_crs="EPSG:5070"
    )
    shared = geom_a.boundary.intersection(geom_b.boundary)
    lines = extract_lines(shared)
    points = sample_line_points(lines, spacing_m)
    values_a = read_samples(cog_a, points) if points else np.array([], dtype=np.uint16)
    values_b = read_samples(cog_b, points) if points else np.array([], dtype=np.uint16)
    valid_a = values_a != NODATA_U16
    valid_b = values_b != NODATA_U16
    valid_pair = valid_a & valid_b
    diff_m = (
        np.abs(
            values_a[valid_pair].astype(np.int32)
            - values_b[valid_pair].astype(np.int32)
        )
        / 10.0
        if np.any(valid_pair)
        else np.array([], dtype=np.float32)
    )
    low_threshold_dm = round(3.0 * 0.3048 * 10.0)
    either_low = ((values_a <= low_threshold_dm) & valid_a) | (
        (values_b <= low_threshold_dm) & valid_b
    )

    def percentile(values: np.ndarray, q: float) -> float | None:
        if values.size == 0:
            return None
        return round(float(np.percentile(values, q)), 3)

    return {
        "regions": [asdict(region_a), asdict(region_b)],
        "shared_boundary_length_m": round(float(sum(line.length for line in lines)), 2),
        "sample_spacing_m": spacing_m,
        "sample_count": len(points),
        "valid_a_count": int(np.count_nonzero(valid_a)),
        "valid_b_count": int(np.count_nonzero(valid_b)),
        "valid_pair_count": int(np.count_nonzero(valid_pair)),
        "either_low_3ft_count": int(np.count_nonzero(either_low)),
        "either_low_3ft_pct": round(
            int(np.count_nonzero(either_low)) * 100.0 / len(points), 3
        )
        if points
        else None,
        "abs_diff_m": {
            "mean": round(float(np.mean(diff_m)), 3) if diff_m.size else None,
            "p50": percentile(diff_m, 50),
            "p90": percentile(diff_m, 90),
            "p95": percentile(diff_m, 95),
            "max": round(float(np.max(diff_m)), 3) if diff_m.size else None,
            "within_0p3m_pct": round(float(np.mean(diff_m <= 0.3) * 100.0), 3)
            if diff_m.size
            else None,
            "within_1m_pct": round(float(np.mean(diff_m <= 1.0) * 100.0), 3)
            if diff_m.size
            else None,
        },
    }


def write_region_report(report_root: Path, result: dict[str, Any]) -> None:
    report_dir = report_root / result["region_id"]
    report_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = Path(result["artifact_dir"])
    preview_src = artifact_dir / "preview.png"
    if preview_src.exists():
        shutil.copyfile(preview_src, report_dir / "preview.png")
    (report_dir / "metrics.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    gate = result["gate_result"]
    checks = gate["checks"]
    metadata = result["metadata"]
    compute = result["estimate"]["compute_bbox"]
    output = result["estimate"]["output_bbox"]
    lines = [
        f"# Buffered HUC4 HAND: {result['region']['huc4']} {result['region']['name']}",
        "",
        f"- Automated result: **{'PASS' if gate['automated_pass'] else 'FAIL'}**.",
        f"- Buffer: `{result['buffer_km']} km`.",
        f"- Output: polygon-clipped COG at `{result['source_cog']}`.",
        f"- DEM resolution: `{metadata['dem_resolution_m']}m`.",
        f"- Wall time: `{gate['wall_time_s']}s`; peak RSS: `{gate['peak_rss_mb']} MB`; source COG: `{format_bytes(gate['source_cog_bytes'])}`.",
        f"- Valid clipped HAND cells: `{gate['valid_cell_pct']}%`; 3ft area: `{gate['area_3ft_pct']}%`.",
        "",
        "## Size",
        "",
        f"- Compute bbox cells: `{compute['cells']:,}`.",
        f"- Output bbox cells before polygon mask: `{output['cells']:,}`.",
        "",
        "## Caveat",
        "",
        "- This proves a buffered, polygon-clipped output for one region. Boundary correctness is decided by the pair seam report, not this single-region report.",
    ]
    (report_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_pair_report(
    *,
    report_root: Path,
    huc4_a: str,
    huc4_b: str,
    buffer_km: float,
    region_results: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> None:
    report_dir = report_root / pair_id(huc4_a, huc4_b, buffer_km)
    report_dir.mkdir(parents=True, exist_ok=True)
    region_memory_pass = all(
        result["gate_result"]["checks"]["peak_rss"] for result in region_results
    )
    region_time_storage_pass = all(
        result["gate_result"]["checks"]["wall_time"]
        and result["gate_result"]["checks"]["source_cog_size"]
        for result in region_results
    )
    seam_pass = (
        metrics["sample_count"] > 0
        and metrics["either_low_3ft_pct"] is not None
        and metrics["either_low_3ft_pct"] < 10.0
    )
    automated_pass = region_memory_pass and region_time_storage_pass and seam_pass
    payload = {
        "huc4_pair": sorted([huc4_a, huc4_b]),
        "buffer_km": buffer_km,
        "decision": {
            "automated_pass": automated_pass,
            "region_memory_pass": region_memory_pass,
            "region_time_storage_pass": region_time_storage_pass,
            "seam_pass": seam_pass,
        },
        "regions": region_results,
        "seam_metrics": metrics,
    }
    (report_dir / "metrics.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        f"# Boundary HAND Gate: {' / '.join(sorted([huc4_a, huc4_b]))}",
        "",
        f"- Automated result: **{'PASS' if automated_pass else 'FAIL'}**.",
        f"- Seam result: **{'PASS' if seam_pass else 'FAIL'}**.",
        f"- Region compute budget: **{'PASS' if region_memory_pass else 'FAIL'}** for memory; **{'PASS' if region_time_storage_pass else 'FAIL'}** for wall time and COG size.",
        f"- Buffer: `{buffer_km} km`.",
        f"- Shared boundary length: `{metrics['shared_boundary_length_m']} m`.",
        f"- Boundary samples: `{metrics['sample_count']}`; valid paired samples: `{metrics['valid_pair_count']}`.",
        f"- Either-side <=3ft samples: `{metrics['either_low_3ft_pct']}%`.",
        f"- Abs diff p50/p95/max: `{metrics['abs_diff_m']['p50']}` / `{metrics['abs_diff_m']['p95']}` / `{metrics['abs_diff_m']['max']}` m.",
        "",
        "## Region Runs",
        "",
        "| HUC4 | Name | Wall s | Peak RSS MB | COG | Valid % | 3ft % |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for result in region_results:
        gate = result["gate_result"]
        region = result["region"]
        lines.append(
            f"| `{region['huc4']}` | {region['name']} | {gate['wall_time_s']} | {gate['peak_rss_mb']} | {format_bytes(gate['source_cog_bytes'])} | {gate['valid_cell_pct']} | {gate['area_3ft_pct']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- This gate checks whether buffered, polygon-clipped region outputs avoid synthetic low-HAND seams along the shared HUC boundary.",
            "- The percentage of <=3ft boundary samples is the main automated seam flag; visual preview review is still required before CONUS batching.",
            "- A seam pass with a memory fail means the boundary method is directionally sound, but the in-memory per-HUC implementation is not the CONUS builder.",
        ]
    )
    (report_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_region(args: argparse.Namespace) -> dict[str, Any]:
    result = run_buffered_region(
        huc4=args.huc4,
        buffer_km=args.buffer_km,
        data_root=args.data_root,
        artifact_root=args.artifact_root,
        dem_resolution_m=args.dem_resolution_m,
        stream_burn_depth_m=args.stream_burn_depth_m,
        accumulation_threshold_km2=args.flow_accumulation_drain_threshold_km2,
    )
    write_region_report(args.report_root, result)
    print(json.dumps(result["gate_result"], indent=2, sort_keys=True))
    print(f"Wrote {args.report_root / result['region_id']}")
    return result


def load_region_result(
    report_root: Path, huc4: str, buffer_km: float
) -> dict[str, Any]:
    region, _ = fetch_huc4_shape(huc4)
    region_id = boundary_region_id(region, buffer_km)
    return json.loads((report_root / region_id / "metrics.json").read_text())


def run_pair(args: argparse.Namespace) -> None:
    results = [build_region_for_pair(args, huc4) for huc4 in args.huc4]
    cog_a = Path(results[0]["source_cog"])
    cog_b = Path(results[1]["source_cog"])
    metrics = seam_metrics(
        huc4_a=args.huc4[0],
        huc4_b=args.huc4[1],
        cog_a=cog_a,
        cog_b=cog_b,
        spacing_m=args.seam_sample_spacing_m,
    )
    write_pair_report(
        report_root=args.report_root,
        huc4_a=args.huc4[0],
        huc4_b=args.huc4[1],
        buffer_km=args.buffer_km,
        region_results=results,
        metrics=metrics,
    )
    print(json.dumps(metrics, indent=2, sort_keys=True))
    print(
        f"Wrote {args.report_root / pair_id(args.huc4[0], args.huc4[1], args.buffer_km)}"
    )


def build_region_for_pair(args: argparse.Namespace, huc4: str) -> dict[str, Any]:
    result = run_buffered_region(
        huc4=huc4,
        buffer_km=args.buffer_km,
        data_root=args.data_root,
        artifact_root=args.artifact_root,
        dem_resolution_m=args.dem_resolution_m,
        stream_burn_depth_m=args.stream_burn_depth_m,
        accumulation_threshold_km2=args.flow_accumulation_drain_threshold_km2,
    )
    write_region_report(args.report_root, result)
    return result


def estimate(args: argparse.Namespace) -> None:
    rows = []
    for huc4 in args.huc4:
        region, geometry = fetch_huc4_shape(huc4)
        estimate_result = estimate_buffered_shape(
            geometry, buffer_km=args.buffer_km, resolution_m=args.dem_resolution_m
        )
        rows.append(
            {
                "region": asdict(region),
                "region_id": boundary_region_id(region, args.buffer_km),
                "estimate": {
                    "compute_bbox": asdict(estimate_result.compute_bbox),
                    "output_bbox": asdict(estimate_result.output_bbox),
                    "compute_bbox_lonlat": estimate_result.compute_bbox_lonlat,
                    "output_bbox_lonlat": estimate_result.output_bbox_lonlat,
                },
            }
        )
    print(json.dumps(rows, indent=2, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "--buffer-km", type=float, default=DEFAULT_BOUNDARY_BUFFER_KM
        )
        subparser.add_argument(
            "--dem-resolution-m", type=int, default=DEFAULT_DEM_RESOLUTION_M
        )
        subparser.add_argument(
            "--stream-burn-depth-m",
            type=float,
            default=DEFAULT_STREAM_BURN_DEPTH_M,
        )
        subparser.add_argument(
            "--flow-accumulation-drain-threshold-km2",
            type=float,
            default=DEFAULT_ACCUMULATION_THRESHOLD_KM2,
        )
        subparser.add_argument(
            "--data-root",
            type=Path,
            default=Path(os.getenv("FLOODMAP_DATA_ROOT", "data")),
        )
        subparser.add_argument("--artifact-root", type=Path, default=Path("scratch"))
        subparser.add_argument(
            "--report-root", type=Path, default=Path("docs/qa/hand-boundary")
        )

    estimate_parser = subparsers.add_parser("estimate")
    add_common(estimate_parser)
    estimate_parser.add_argument("--huc4", action="append", default=[])

    build_parser = subparsers.add_parser("build")
    add_common(build_parser)
    build_parser.add_argument("--huc4", required=True)

    pair_parser = subparsers.add_parser("pair")
    add_common(pair_parser)
    pair_parser.add_argument("--huc4", action="append", default=[])
    pair_parser.add_argument(
        "--seam-sample-spacing-m", type=float, default=DEFAULT_SEAM_SAMPLE_SPACING_M
    )

    seam_parser = subparsers.add_parser("seam")
    add_common(seam_parser)
    seam_parser.add_argument("--huc4", action="append", default=[])
    seam_parser.add_argument(
        "--seam-sample-spacing-m", type=float, default=DEFAULT_SEAM_SAMPLE_SPACING_M
    )

    args = parser.parse_args()
    if args.command in {"estimate", "pair", "seam"} and not args.huc4:
        args.huc4 = list(DEFAULT_BOUNDARY_PAIR)
    if args.command in {"pair", "seam"} and len(args.huc4) != 2:
        parser.error("pair/seam requires exactly two --huc4 values")
    return args


def main() -> None:
    args = parse_args()
    if args.command == "estimate":
        estimate(args)
    elif args.command == "build":
        build_region(args)
    elif args.command == "pair":
        run_pair(args)
    elif args.command == "seam":
        results = [
            load_region_result(args.report_root, huc4, args.buffer_km)
            for huc4 in args.huc4
        ]
        metrics = seam_metrics(
            huc4_a=args.huc4[0],
            huc4_b=args.huc4[1],
            cog_a=Path(results[0]["source_cog"]),
            cog_b=Path(results[1]["source_cog"]),
            spacing_m=args.seam_sample_spacing_m,
        )
        write_pair_report(
            report_root=args.report_root,
            huc4_a=args.huc4[0],
            huc4_b=args.huc4[1],
            buffer_km=args.buffer_km,
            region_results=results,
            metrics=metrics,
        )
        print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
