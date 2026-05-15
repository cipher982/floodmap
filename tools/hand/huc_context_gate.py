#!/usr/bin/env python3
"""Build a HUC output unit using a larger hydrologic compute context."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.hand.huc_boundary_gate import (  # noqa: E402
    DEFAULT_BOUNDARY_BUFFER_KM,
    clip_to_polygon,
    distance_tag,
    estimate_buffered_shape,
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
from tools.hand.huc_unit_gate import (  # noqa: E402
    DEFAULT_HUC,
    DEFAULT_HUC_LEVEL,
    DEFAULT_SAMPLE_COUNT,
    diff_against_reference,
    fetch_huc_unit,
)
from tools.prototypes import generate_birmingham_drainage as hand_gen  # noqa: E402

DEFAULT_COMPUTE_HUC_LEVEL = 6


def parent_huc_code(output_code: str, compute_level: int) -> str:
    if compute_level > len(output_code):
        raise ValueError(
            f"Cannot derive HUC{compute_level} parent from code {output_code!r}."
        )
    return output_code[:compute_level]


def context_region_id(output_unit, compute_unit, buffer_km: float) -> str:
    return (
        f"huc{output_unit.level}-{output_unit.code}-{slugify(output_unit.name)}"
        f"-context-huc{compute_unit.level}-{compute_unit.code}"
        f"-buffer{distance_tag(buffer_km)}km-clipped"
    )


def run_context_unit(
    *,
    output_level: int,
    output_code: str,
    compute_level: int,
    compute_code: str,
    buffer_km: float,
    data_root: Path,
    artifact_root: Path,
    report_root: Path,
    dem_resolution_m: int,
    stream_burn_depth_m: float,
    accumulation_threshold_km2: float,
    reference_cog: Path | None,
    sample_count: int,
    seed: int,
) -> dict[str, Any]:
    if output_level < compute_level:
        raise ValueError(
            "Compute HUC must be the same level as or parent of output HUC."
        )
    if not output_code.startswith(compute_code):
        raise ValueError(
            f"Output HUC{output_level} {output_code} is not inside "
            f"compute HUC{compute_level} {compute_code}."
        )

    output_unit, output_geometry_wgs84 = fetch_huc_unit(output_level, output_code)
    compute_unit, compute_geometry_wgs84 = fetch_huc_unit(compute_level, compute_code)
    estimate = estimate_buffered_shape(
        compute_geometry_wgs84, buffer_km=buffer_km, resolution_m=dem_resolution_m
    )
    region_id = context_region_id(output_unit, compute_unit, buffer_km)
    artifact_dir = artifact_root / "hand-context" / region_id
    cog_path = source_cog_path(data_root, region_id)

    hand_gen.configure_runtime(
        hand_gen.PrototypeConfig(
            name=region_id,
            title=(
                f"{output_unit.name} HUC{output_unit.level} HAND "
                f"with HUC{compute_unit.level} context"
            ),
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
        f"Building {region_id}: compute HUC{compute_level} {compute_code}, "
        f"output HUC{output_level} {output_code}.",
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
        geometry_wgs84=output_geometry_wgs84,
    )
    target_flowlines = intersecting_flowlines(flowlines, output_geometry_wgs84, crs)
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
    metadata["huc_context_gate"] = {
        "output_unit": asdict(output_unit),
        "compute_unit": asdict(compute_unit),
        "buffer_km": buffer_km,
        "polygon_clipped_to_output_huc": True,
        "compute_bbox_lonlat": list(estimate.compute_bbox_lonlat),
        "output_huc_bbox_lonlat": list(output_unit.bbox),
        "compute_bbox_estimate": asdict(estimate.compute_bbox),
    }
    hand_gen.META_PATH.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    result = {
        "output_unit": asdict(output_unit),
        "compute_unit": asdict(compute_unit),
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
            "compute_bbox_lonlat": estimate.compute_bbox_lonlat,
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
    if reference_cog is not None:
        diff_against_reference(
            reference_cog=reference_cog,
            candidate_cog=cog_path,
            report_root=report_root,
            region_id=region_id,
            sample_count=sample_count,
            seed=seed,
        )
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
    thresholds = metadata["threshold_stats_ft"]
    lines = [
        (
            f"# HUC{result['output_unit']['level']} Context HAND Unit: "
            f"{result['output_unit']['code']} {result['output_unit']['name']}"
        ),
        "",
        f"- Output: `{result['source_cog']}`.",
        (
            f"- Compute context: HUC{result['compute_unit']['level']} "
            f"`{result['compute_unit']['code']}` {result['compute_unit']['name']}."
        ),
        f"- Wall time: `{build['wall_time_s']}s` ({result['checks']['wall_time']}).",
        f"- Peak RSS: `{build['peak_rss_mb']} MB` ({result['checks']['peak_rss']}).",
        f"- Source COG: `{format_bytes(build['source_cog_bytes'])}` ({result['checks']['source_cog_size']}).",
        f"- Valid clipped cells: `{valid_pct}%`.",
        f"- 3ft/6ft/10ft area: `{thresholds['3']['percent']}%` / `{thresholds['6']['percent']}%` / `{thresholds['10']['percent']}%`.",
        f"- Compute bbox cells: `{result['estimate']['compute_bbox']['cells']:,}`.",
    ]
    (report_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-huc-level", type=int, default=DEFAULT_HUC_LEVEL)
    parser.add_argument("--output-huc", default=DEFAULT_HUC)
    parser.add_argument(
        "--compute-huc-level", type=int, default=DEFAULT_COMPUTE_HUC_LEVEL
    )
    parser.add_argument("--compute-huc")
    parser.add_argument("--buffer-km", type=float, default=DEFAULT_BOUNDARY_BUFFER_KM)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("scratch"))
    parser.add_argument(
        "--report-root", type=Path, default=Path("docs/qa/hand-context")
    )
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
    parser.add_argument("--reference-cog", type=Path)
    parser.add_argument("--sample-count", type=int, default=DEFAULT_SAMPLE_COUNT)
    parser.add_argument("--seed", type=int, default=23)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    compute_code = args.compute_huc or parent_huc_code(
        args.output_huc, args.compute_huc_level
    )
    result = run_context_unit(
        output_level=args.output_huc_level,
        output_code=args.output_huc,
        compute_level=args.compute_huc_level,
        compute_code=compute_code,
        buffer_km=args.buffer_km,
        data_root=args.data_root,
        artifact_root=args.artifact_root,
        report_root=args.report_root,
        dem_resolution_m=args.dem_resolution_m,
        stream_burn_depth_m=args.stream_burn_depth_m,
        accumulation_threshold_km2=args.flow_accumulation_drain_threshold_km2,
        reference_cog=args.reference_cog,
        sample_count=args.sample_count,
        seed=args.seed,
    )
    print(json.dumps(result["build"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
