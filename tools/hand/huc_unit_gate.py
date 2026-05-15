#!/usr/bin/env python3
"""Build buffered, polygon-clipped HAND outputs for arbitrary HUC levels."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject
from rasterio.windows import Window
from rasterio.windows import transform as window_transform

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.hand.huc_boundary_gate import (  # noqa: E402
    DEFAULT_BOUNDARY_BUFFER_KM,
    NODATA_U16,
    clip_to_polygon,
    distance_tag,
    estimate_buffered_shape,
    fetch_huc4_shape,
    format_bytes,
    intersecting_flowlines,
    source_cog_path,
)
from tools.hand.huc_scale_gate import (  # noqa: E402
    DEFAULT_ACCUMULATION_THRESHOLD_KM2,
    DEFAULT_DEM_RESOLUTION_M,
    DEFAULT_MAX_RSS_MB,
    DEFAULT_MAX_SOURCE_COG_BYTES,
    DEFAULT_MAX_WALL_S,
    DEFAULT_STREAM_BURN_DEPTH_M,
    slugify,
)
from tools.prototypes import generate_birmingham_drainage as hand_gen  # noqa: E402

DEFAULT_HUC_LEVEL = 8
DEFAULT_HUC = "01070006"
DEFAULT_SAMPLE_COUNT = 250_000
LOW_THRESHOLDS_DM = {
    "3ft": round(3.0 * 0.3048 * 10.0),
    "6ft": round(6.0 * 0.3048 * 10.0),
    "10ft": round(10.0 * 0.3048 * 10.0),
}


@dataclass(frozen=True)
class HucUnit:
    level: int
    code: str
    name: str
    states: str
    area_km2: float
    bbox: tuple[float, float, float, float]


def unit_region_id(unit: HucUnit, buffer_km: float) -> str:
    return (
        f"huc{unit.level}-{unit.code}-{slugify(unit.name)}"
        f"-buffer{distance_tag(buffer_km)}km-clipped"
    )


def fetch_huc_unit(level: int, code: str) -> tuple[HucUnit, Any]:
    if level == 4:
        region, geometry = fetch_huc4_shape(code)
        return (
            HucUnit(
                level=4,
                code=region.huc4,
                name=region.name,
                states=region.states,
                area_km2=region.area_km2,
                bbox=region.bbox,
            ),
            geometry,
        )

    from pygeohydro import WBD

    field = f"huc{level}"
    wbd = WBD(field, outfields=[field, "name", "areasqkm", "states"])
    gdf = wbd.byids(field, [code])
    if len(gdf) != 1:
        raise RuntimeError(f"Expected one WBD {field} row for {code}, got {len(gdf)}")
    row = gdf.iloc[0]
    return (
        HucUnit(
            level=level,
            code=str(row[field]),
            name=str(row["name"]),
            states=str(row["states"]),
            area_km2=float(row["areasqkm"]),
            bbox=tuple(float(value) for value in row.geometry.bounds),
        ),
        row.geometry,
    )


def run_buffered_unit(
    *,
    level: int,
    code: str,
    buffer_km: float,
    data_root: Path,
    artifact_root: Path,
    report_root: Path,
    dem_resolution_m: int,
    stream_burn_depth_m: float,
    accumulation_threshold_km2: float,
) -> dict[str, Any]:
    unit, geometry_wgs84 = fetch_huc_unit(level, code)
    estimate = estimate_buffered_shape(
        geometry_wgs84, buffer_km=buffer_km, resolution_m=dem_resolution_m
    )
    region_id = unit_region_id(unit, buffer_km)
    artifact_dir = artifact_root / "hand-unit" / region_id
    cog_path = source_cog_path(data_root, region_id)

    hand_gen.configure_runtime(
        hand_gen.PrototypeConfig(
            name=region_id,
            title=f"{unit.name} HUC{unit.level} HAND",
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
    print(
        f"Building {region_id}: compute bbox {estimate.compute_bbox_lonlat}.",
        flush=True,
    )
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
    metadata["huc_unit_gate"] = {
        "level": unit.level,
        "code": unit.code,
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
        "unit": asdict(unit),
        "region_id": region_id,
        "source_cog": str(cog_path),
        "artifact_dir": str(artifact_dir),
        "params": {
            "buffer_km": buffer_km,
            "dem_resolution_m": dem_resolution_m,
            "stream_burn_depth_m": stream_burn_depth_m,
            "accumulation_threshold_km2": accumulation_threshold_km2,
        },
        "estimate": {
            "compute_bbox": asdict(estimate.compute_bbox),
            "output_bbox": asdict(estimate.output_bbox),
            "compute_bbox_lonlat": estimate.compute_bbox_lonlat,
            "output_bbox_lonlat": estimate.output_bbox_lonlat,
        },
        "metadata": metadata,
        "checks": {
            "wall_time": build_metrics["wall_time_s"] <= DEFAULT_MAX_WALL_S,
            "peak_rss": build_metrics["peak_rss_mb"] <= DEFAULT_MAX_RSS_MB,
            "source_cog_size": build_metrics["source_cog_bytes"]
            <= DEFAULT_MAX_SOURCE_COG_BYTES,
        },
        "build": build_metrics,
    }
    write_report(report_root, result)
    return result


def write_report(report_root: Path, result: dict[str, Any]) -> None:
    report_dir = report_root / result["region_id"]
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "metrics.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    build = result["build"]
    metadata = result["metadata"]
    valid_cells = int(metadata["valid_hand_cells"])
    nodata_cells = int(metadata["nodata_cells"])
    total_cells = valid_cells + nodata_cells
    valid_pct = round(valid_cells * 100.0 / total_cells, 2) if total_cells else None
    threshold = metadata["threshold_stats_ft"]["3"]["percent"]
    lines = [
        f"# HUC{result['unit']['level']} HAND Unit: {result['unit']['code']} {result['unit']['name']}",
        "",
        f"- Output: `{result['source_cog']}`.",
        f"- Wall time: `{build['wall_time_s']}s` ({result['checks']['wall_time']}).",
        f"- Peak RSS: `{build['peak_rss_mb']} MB` ({result['checks']['peak_rss']}).",
        f"- Source COG: `{format_bytes(build['source_cog_bytes'])}` ({result['checks']['source_cog_size']}).",
        f"- Valid clipped cells: `{valid_pct}%`; 3ft area: `{threshold}%`.",
        f"- Compute bbox cells: `{result['estimate']['compute_bbox']['cells']:,}`.",
        f"- Output bbox cells before polygon mask: `{result['estimate']['output_bbox']['cells']:,}`.",
    ]
    (report_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def report_existing(
    *,
    metadata_path: Path,
    report_root: Path,
) -> dict[str, Any]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    gate = metadata["huc_unit_gate"]
    unit = HucUnit(
        level=int(gate["level"]),
        code=str(gate["code"]),
        name=str(metadata["title"]).removesuffix(f" HUC{gate['level']} HAND"),
        states="",
        area_km2=0.0,
        bbox=tuple(float(value) for value in metadata["bbox_lonlat"]),
    )
    region_id = str(metadata["name"])
    result = {
        "unit": asdict(unit),
        "region_id": region_id,
        "source_cog": str(metadata["generated_assets"]["source_cog"]),
        "artifact_dir": str(metadata_path.parent),
        "params": {
            "buffer_km": gate["buffer_km"],
            "dem_resolution_m": metadata["dem_resolution_m"],
            "stream_burn_depth_m": metadata["routing"]["stream_burn_depth_m"],
            "accumulation_threshold_km2": metadata["routing"][
                "accumulation_drain_threshold_km2"
            ],
        },
        "estimate": {
            "compute_bbox": gate["compute_bbox_estimate"],
            "output_bbox": gate["output_bbox_estimate"],
            "compute_bbox_lonlat": gate["compute_bbox_lonlat"],
            "output_bbox_lonlat": gate["output_bbox_lonlat"],
        },
        "metadata": metadata,
        "checks": {
            "wall_time": metadata["build"]["wall_time_s"] <= DEFAULT_MAX_WALL_S,
            "peak_rss": metadata["build"]["peak_rss_mb"] <= DEFAULT_MAX_RSS_MB,
            "source_cog_size": metadata["build"]["source_cog_bytes"]
            <= DEFAULT_MAX_SOURCE_COG_BYTES,
        },
        "build": metadata["build"],
    }
    write_report(report_root, result)
    return result


def percentile(values: np.ndarray, q: float) -> float | None:
    if values.size == 0:
        return None
    return round(float(np.percentile(values, q)), 3)


def diff_against_reference(
    *,
    reference_cog: Path,
    candidate_cog: Path,
    report_root: Path,
    region_id: str,
    sample_count: int,
    seed: int,
    reference_note: str | None = None,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    sampled_diffs: list[np.ndarray] = []
    counts: dict[str, int] = {
        "candidate_cells": 0,
        "candidate_valid_cells": 0,
        "reference_valid_cells_on_candidate_grid": 0,
        "valid_pair_cells": 0,
        "gt_1m_cells": 0,
    }
    threshold_counts = {
        name: {
            "reference_cells": 0,
            "candidate_cells": 0,
            "intersection_cells": 0,
            "union_cells": 0,
        }
        for name in LOW_THRESHOLDS_DM
    }

    with rasterio.open(reference_cog) as ref, rasterio.open(candidate_cog) as cand:
        crs_info = {
            "reference": str(ref.crs),
            "candidate": str(cand.crs),
            "match": str(ref.crs) == str(cand.crs),
        }
        reprojection = {
            "performed": not crs_info["match"],
            "resampling": Resampling.nearest.name,
            "note": (
                "Reference was reprojected onto the candidate grid before diffing; "
                "cross-CRS diffs are approximate smoke metrics."
                if not crs_info["match"]
                else "No CRS reprojection was required."
            ),
        }
        sample_rate = sample_count / max(1, cand.width * cand.height)
        for row_start in range(0, cand.height, 512):
            row_count = min(512, cand.height - row_start)
            window = Window(0, row_start, cand.width, row_count)
            candidate = cand.read(1, window=window)
            reference = np.full(candidate.shape, NODATA_U16, dtype=np.uint16)
            reproject(
                source=rasterio.band(ref, 1),
                destination=reference,
                src_transform=ref.transform,
                src_crs=ref.crs,
                src_nodata=NODATA_U16,
                dst_transform=window_transform(window, cand.transform),
                dst_crs=cand.crs,
                dst_nodata=NODATA_U16,
                resampling=Resampling.nearest,
            )
            cand_valid = candidate != NODATA_U16
            ref_valid = reference != NODATA_U16
            valid_pair = cand_valid & ref_valid
            counts["candidate_cells"] += int(candidate.size)
            counts["candidate_valid_cells"] += int(np.count_nonzero(cand_valid))
            counts["reference_valid_cells_on_candidate_grid"] += int(
                np.count_nonzero(ref_valid)
            )
            counts["valid_pair_cells"] += int(np.count_nonzero(valid_pair))
            if np.any(valid_pair):
                diff_dm = np.abs(
                    candidate[valid_pair].astype(np.int32)
                    - reference[valid_pair].astype(np.int32)
                )
                counts["gt_1m_cells"] += int(np.count_nonzero(diff_dm > 10))
                take = rng.random(diff_dm.size) < sample_rate
                if np.any(take):
                    sampled_diffs.append(diff_dm[take].astype(np.uint16))

            for name, threshold_dm in LOW_THRESHOLDS_DM.items():
                ref_low = ref_valid & (reference <= threshold_dm)
                cand_low = cand_valid & (candidate <= threshold_dm)
                threshold_counts[name]["reference_cells"] += int(
                    np.count_nonzero(ref_low)
                )
                threshold_counts[name]["candidate_cells"] += int(
                    np.count_nonzero(cand_low)
                )
                threshold_counts[name]["intersection_cells"] += int(
                    np.count_nonzero(ref_low & cand_low)
                )
                threshold_counts[name]["union_cells"] += int(
                    np.count_nonzero(ref_low | cand_low)
                )

    diffs_dm = (
        np.concatenate(sampled_diffs)
        if sampled_diffs
        else np.array([], dtype=np.uint16)
    )
    diffs_m = diffs_dm.astype(np.float32) / 10.0
    threshold_stats = {}
    for name, values in threshold_counts.items():
        union = values["union_cells"]
        threshold_stats[name] = {
            **values,
            "jaccard": round(values["intersection_cells"] / union, 4)
            if union
            else None,
        }
    result = {
        "reference_cog": str(reference_cog),
        "candidate_cog": str(candidate_cog),
        "crs": crs_info,
        "reprojection": reprojection,
        "reference_note": reference_note,
        "sample_seed": seed,
        "sample_target": sample_count,
        "sample_count": int(diffs_dm.size),
        "counts": counts,
        "abs_diff_m": {
            "mean": round(float(np.mean(diffs_m)), 3) if diffs_m.size else None,
            "p50": percentile(diffs_m, 50),
            "p90": percentile(diffs_m, 90),
            "p95": percentile(diffs_m, 95),
            "p99": percentile(diffs_m, 99),
            "max_sampled": round(float(np.max(diffs_m)), 3) if diffs_m.size else None,
            "within_1m_pct": round(float(np.mean(diffs_m <= 1.0) * 100.0), 3)
            if diffs_m.size
            else None,
        },
        "thresholds": threshold_stats,
    }
    report_dir = report_root / region_id
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "diff-metrics.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        "# HAND Candidate vs Reference Diff",
        "",
        f"- Reference CRS / candidate CRS: `{crs_info['reference']}` / `{crs_info['candidate']}`.",
        f"- Reprojection: `{reprojection['performed']}` with `{reprojection['resampling']}` resampling.",
        f"- Samples: `{result['sample_count']}` of target `{result['sample_target']}`.",
        f"- Abs diff p50/p95/p99/max sampled: `{result['abs_diff_m']['p50']}` / `{result['abs_diff_m']['p95']}` / `{result['abs_diff_m']['p99']}` / `{result['abs_diff_m']['max_sampled']}` m.",
        f"- Within 1m: `{result['abs_diff_m']['within_1m_pct']}%`.",
        f"- Cells with >1m diff: `{counts['gt_1m_cells']}`.",
        f"- 3ft/6ft/10ft Jaccard: `{threshold_stats['3ft']['jaccard']}` / `{threshold_stats['6ft']['jaccard']}` / `{threshold_stats['10ft']['jaccard']}`.",
    ]
    if reference_note:
        lines.insert(2, f"- Reference note: {reference_note}")
    (report_dir / "diff-summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--huc-level", type=int, default=DEFAULT_HUC_LEVEL)
    build.add_argument("--huc", default=DEFAULT_HUC)
    build.add_argument("--buffer-km", type=float, default=DEFAULT_BOUNDARY_BUFFER_KM)
    build.add_argument("--data-root", type=Path, default=Path("data"))
    build.add_argument("--artifact-root", type=Path, default=Path("scratch"))
    build.add_argument("--report-root", type=Path, default=Path("docs/qa/hand-unit"))
    build.add_argument("--dem-resolution-m", type=int, default=DEFAULT_DEM_RESOLUTION_M)
    build.add_argument(
        "--stream-burn-depth-m", type=float, default=DEFAULT_STREAM_BURN_DEPTH_M
    )
    build.add_argument(
        "--flow-accumulation-drain-threshold-km2",
        type=float,
        default=DEFAULT_ACCUMULATION_THRESHOLD_KM2,
    )

    diff = subparsers.add_parser("diff")
    diff.add_argument("--reference-cog", type=Path, required=True)
    diff.add_argument("--candidate-cog", type=Path, required=True)
    diff.add_argument("--region-id", required=True)
    diff.add_argument("--report-root", type=Path, default=Path("docs/qa/hand-unit"))
    diff.add_argument("--sample-count", type=int, default=DEFAULT_SAMPLE_COUNT)
    diff.add_argument("--seed", type=int, default=11)
    diff.add_argument("--reference-note")

    report = subparsers.add_parser("report-existing")
    report.add_argument("--metadata-path", type=Path, required=True)
    report.add_argument("--report-root", type=Path, default=Path("docs/qa/hand-unit"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "build":
        result = run_buffered_unit(
            level=args.huc_level,
            code=args.huc,
            buffer_km=args.buffer_km,
            data_root=args.data_root,
            artifact_root=args.artifact_root,
            report_root=args.report_root,
            dem_resolution_m=args.dem_resolution_m,
            stream_burn_depth_m=args.stream_burn_depth_m,
            accumulation_threshold_km2=args.flow_accumulation_drain_threshold_km2,
        )
        print(json.dumps(result["build"], indent=2, sort_keys=True))
    elif args.command == "diff":
        result = diff_against_reference(
            reference_cog=args.reference_cog,
            candidate_cog=args.candidate_cog,
            report_root=args.report_root,
            region_id=args.region_id,
            sample_count=args.sample_count,
            seed=args.seed,
            reference_note=args.reference_note,
        )
        print(json.dumps(result["abs_diff_m"], indent=2, sort_keys=True))
    elif args.command == "report-existing":
        result = report_existing(
            metadata_path=args.metadata_path,
            report_root=args.report_root,
        )
        print(json.dumps(result["build"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
