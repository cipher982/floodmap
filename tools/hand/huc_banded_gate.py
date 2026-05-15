#!/usr/bin/env python3
"""Gate 7 bounded-memory banded HAND builder and diff QA."""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import rasterio.features
from PIL import Image
from rasterio.shutil import copy as rio_copy
from rasterio.windows import Window
from rasterio.windows import transform as window_transform
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.hand.huc_boundary_gate import (  # noqa: E402
    DEFAULT_BOUNDARY_BUFFER_KM,
    NODATA_U16,
    boundary_region_id,
    distance_tag,
    estimate_buffered_shape,
    fetch_huc4_shape,
    format_bytes,
    lonlat_bounds,
    project_geometry,
    source_cog_path,
)
from tools.hand.huc_scale_gate import (  # noqa: E402
    DEFAULT_ACCUMULATION_THRESHOLD_KM2,
    DEFAULT_DEM_RESOLUTION_M,
    DEFAULT_MAX_RSS_MB,
    DEFAULT_MAX_SOURCE_COG_BYTES,
    DEFAULT_MAX_WALL_S,
    DEFAULT_STREAM_BURN_DEPTH_M,
)
from tools.prototypes import generate_birmingham_drainage as hand_gen  # noqa: E402

DEFAULT_HUC4 = "0107"
DEFAULT_BAND_ROWS = 6000
DEFAULT_OVERLAP_M = 30_000.0
DEFAULT_SAMPLE_COUNT = 250_000
LOW_THRESHOLD_DM = round(3.0 * 0.3048 * 10.0)
DIFF_THRESHOLD_DM = 10
DEFAULT_ATTRIBUTION_EDGE_PIXELS = 20
DEFAULT_DRAIN_ADJACENT_DM = 1


def banded_region_id(region, buffer_km: float, overlap_m: float, band_rows: int) -> str:
    return (
        f"{boundary_region_id(region, buffer_km)}"
        f"-banded-overlap{distance_tag(overlap_m / 1000.0)}km-rows{band_rows}"
    )


def axis_from_transform(
    transform, width: int, height: int
) -> tuple[np.ndarray, np.ndarray]:
    cols = np.arange(width, dtype=np.float64)
    rows = np.arange(height, dtype=np.float64)
    x = transform.c + transform.a * (cols + 0.5)
    y = transform.f + transform.e * (rows + 0.5)
    return x, y


def encode_hand_window(
    hand: np.ndarray,
    band_x: np.ndarray,
    band_y: np.ndarray,
    target_x: np.ndarray,
    target_y: np.ndarray,
    *,
    target_transform,
    polygon_geometry,
) -> np.ndarray:
    col = hand_gen.nearest_axis_indices(band_x, target_x)
    row = hand_gen.nearest_axis_indices(band_y, target_y)
    sampled = hand[np.ix_(row, col)]
    inside_band = (
        (target_x >= band_x.min())
        & (target_x <= band_x.max())
        & (target_y[:, None] >= band_y.min())
        & (target_y[:, None] <= band_y.max())
    )
    polygon_mask = rasterio.features.geometry_mask(
        [polygon_geometry],
        out_shape=(len(target_y), len(target_x)),
        transform=target_transform,
        invert=True,
        all_touched=True,
    )
    valid = inside_band & polygon_mask & np.isfinite(sampled) & (sampled >= 0)
    safe = np.where(valid, sampled, 0.0)
    encoded = np.asarray(np.round(safe * 10.0), dtype=np.uint16)
    encoded[encoded >= NODATA_U16] = NODATA_U16 - 1
    encoded[~valid] = NODATA_U16
    return encoded


def write_temp_tiff(path: Path, reference_profile: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        **reference_profile,
        "driver": "GTiff",
        "dtype": "uint16",
        "count": 1,
        "nodata": NODATA_U16,
        "compress": "DEFLATE",
        "predictor": 2,
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(path, "w", **profile) as dst:
        for row in range(0, dst.height, 512):
            rows = min(512, dst.height - row)
            nodata = np.full((rows, dst.width), NODATA_U16, dtype=np.uint16)
            dst.write(nodata, 1, window=Window(0, row, dst.width, rows))


def copy_to_cog(temp_path: Path, cog_path: Path) -> None:
    cog_path.parent.mkdir(parents=True, exist_ok=True)
    if cog_path.exists():
        cog_path.unlink()
    rio_copy(
        temp_path,
        cog_path,
        driver="COG",
        compress="DEFLATE",
        predictor=2,
        blocksize=512,
        overview_resampling="nearest",
        nodata=NODATA_U16,
    )


def band_lonlat_bbox(
    *,
    compute_bounds: tuple[float, float, float, float],
    y_min: float,
    y_max: float,
) -> tuple[float, float, float, float]:
    minx, full_miny, maxx, full_maxy = compute_bounds
    geom = box(minx, max(y_min, full_miny), maxx, min(y_max, full_maxy))
    return lonlat_bounds(geom, source_crs="EPSG:5070")


def run_banded_build(
    *,
    huc4: str,
    reference_cog: Path,
    data_root: Path,
    artifact_root: Path,
    report_root: Path,
    buffer_km: float,
    overlap_m: float,
    band_rows: int,
    dem_resolution_m: int,
    stream_burn_depth_m: float,
    accumulation_threshold_km2: float,
) -> dict[str, Any]:
    region, geometry_wgs84 = fetch_huc4_shape(huc4)
    polygon_geometry = project_geometry(
        geometry_wgs84, source_crs="EPSG:4326", target_crs="EPSG:5070"
    )
    buffered = estimate_buffered_shape(
        geometry_wgs84, buffer_km=buffer_km, resolution_m=dem_resolution_m
    )
    compute_geometry = polygon_geometry.buffer(buffer_km * 1000.0)
    compute_bounds = tuple(float(value) for value in compute_geometry.bounds)
    region_id = banded_region_id(region, buffer_km, overlap_m, band_rows)
    artifact_dir = artifact_root / "hand-banded" / region_id
    temp_tiff = artifact_dir / "banded-temp.tif"
    cog_path = source_cog_path(data_root, region_id)

    with rasterio.open(reference_cog) as ref:
        reference_profile = ref.profile.copy()
        target_transform = ref.transform
        target_crs = str(ref.crs)
        target_width = ref.width
        target_height = ref.height

    if target_crs != "EPSG:5070":
        raise RuntimeError(f"Expected EPSG:5070 reference COG, got {target_crs}")

    target_x, target_y = axis_from_transform(
        target_transform, target_width, target_height
    )
    write_temp_tiff(temp_tiff, reference_profile)

    started = time.perf_counter()
    band_reports: list[dict[str, Any]] = []
    total_bands = math.ceil(target_height / band_rows)
    print(
        f"Building {region_id}: {target_width}x{target_height} cells across {total_bands} bands.",
        flush=True,
    )
    with rasterio.open(temp_tiff, "r+") as dst:
        for band_index, row_start in enumerate(range(0, target_height, band_rows)):
            row_stop = min(target_height, row_start + band_rows)
            interior_y = target_y[row_start:row_stop]
            band_y_max = float(interior_y.max() + overlap_m)
            band_y_min = float(interior_y.min() - overlap_m)
            band_bbox = band_lonlat_bbox(
                compute_bounds=compute_bounds, y_min=band_y_min, y_max=band_y_max
            )
            band_artifact_dir = artifact_dir / f"band-{band_index:02d}"
            hand_gen.configure_runtime(
                hand_gen.PrototypeConfig(
                    name=f"{region_id}-band-{band_index:02d}",
                    title=f"{region.name} Banded HAND band {band_index}",
                    bbox_lonlat=band_bbox,
                    dem_resolution_m=dem_resolution_m,
                    stream_min_order=2,
                    stream_burn_depth_m=stream_burn_depth_m,
                    flow_accumulation_drain_threshold_km2=accumulation_threshold_km2,
                    zoom_min=9,
                    zoom_max=12,
                ),
                output_dir=band_artifact_dir,
                source_cog=cog_path,
            )
            band_started = time.perf_counter()
            print(
                f"Band {band_index + 1}/{total_bands}: rows {row_start}-{row_stop}, bbox {tuple(round(value, 5) for value in band_bbox)}.",
                flush=True,
            )
            dem, band_x, band_y, crs = hand_gen.fetch_dem()
            flowlines = hand_gen.fetch_flowlines(crs)
            hand, _upstream_area_km2, _drain_mask, _stream_mask = (
                hand_gen.derive_drainage_height(dem, band_x, band_y, flowlines)
            )
            window = Window(0, row_start, target_width, row_stop - row_start)
            encoded = encode_hand_window(
                hand,
                band_x,
                band_y,
                target_x,
                target_y[row_start:row_stop],
                target_transform=window_transform(window, target_transform),
                polygon_geometry=polygon_geometry,
            )
            dst.write(encoded, 1, window=window)
            band_reports.append(
                {
                    "band_index": band_index,
                    "row_start": row_start,
                    "row_stop": row_stop,
                    "bbox_lonlat": list(band_bbox),
                    "dem_shape": list(dem.shape),
                    "wall_time_s": round(time.perf_counter() - band_started, 2),
                    "peak_rss_mb": round(hand_gen.peak_rss_mb(), 1),
                    "valid_written_cells": int(np.count_nonzero(encoded != NODATA_U16)),
                }
            )
            print(
                f"Band {band_index + 1}/{total_bands} done in {band_reports[-1]['wall_time_s']}s; peak RSS {band_reports[-1]['peak_rss_mb']} MB.",
                flush=True,
            )
            del dem, hand, encoded, flowlines
            gc.collect()

    copy_to_cog(temp_tiff, cog_path)
    build_metrics = {
        "wall_time_s": round(time.perf_counter() - started, 2),
        "peak_rss_mb": round(hand_gen.peak_rss_mb(), 1),
        "source_cog_bytes": cog_path.stat().st_size,
    }
    result = {
        "region": asdict(region),
        "region_id": region_id,
        "reference_cog": str(reference_cog),
        "source_cog": str(cog_path),
        "artifact_dir": str(artifact_dir),
        "params": {
            "buffer_km": buffer_km,
            "overlap_m": overlap_m,
            "band_rows": band_rows,
            "dem_resolution_m": dem_resolution_m,
            "stream_burn_depth_m": stream_burn_depth_m,
            "accumulation_threshold_km2": accumulation_threshold_km2,
        },
        "estimate": {
            "compute_bbox": asdict(buffered.compute_bbox),
            "output_bbox": asdict(buffered.output_bbox),
            "compute_bbox_lonlat": buffered.compute_bbox_lonlat,
            "output_bbox_lonlat": buffered.output_bbox_lonlat,
        },
        "target_grid": {
            "width": target_width,
            "height": target_height,
            "crs": target_crs,
            "transform": list(target_transform)[:6],
        },
        "build": build_metrics,
        "bands": band_reports,
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "banded-build.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_build_report(report_root, result)
    return result


def percentile(values: np.ndarray, q: float) -> float | None:
    if values.size == 0:
        return None
    return round(float(np.percentile(values, q)), 3)


def neighbor_any(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    result = np.zeros(mask.shape, dtype=bool)
    for row_offset in range(3):
        for col_offset in range(3):
            if row_offset == 1 and col_offset == 1:
                continue
            result |= padded[
                row_offset : row_offset + mask.shape[0],
                col_offset : col_offset + mask.shape[1],
            ]
    return result


def band_edge_mask(
    *,
    row_start: int,
    row_count: int,
    height: int,
    band_rows: int,
    edge_pixels: int,
    width: int,
) -> np.ndarray:
    if edge_pixels <= 0 or band_rows <= 0:
        return np.zeros((row_count, width), dtype=bool)
    edges = list(range(band_rows, height, band_rows))
    if not edges:
        return np.zeros((row_count, width), dtype=bool)
    rows = np.arange(row_start, row_start + row_count, dtype=np.int32)
    distance = np.full(rows.shape, height, dtype=np.int32)
    for edge in edges:
        distance = np.minimum(distance, np.abs(rows - edge))
    return np.repeat((distance <= edge_pixels)[:, None], width, axis=1)


def huc_boundary_mask(
    *,
    huc_boundary_buffer,
    window: Window,
    transform,
    row_count: int,
    width: int,
) -> np.ndarray:
    if huc_boundary_buffer is None:
        return np.zeros((row_count, width), dtype=bool)
    return rasterio.features.geometry_mask(
        [huc_boundary_buffer],
        out_shape=(row_count, width),
        transform=window_transform(window, transform),
        invert=True,
        all_touched=True,
    )


def empty_attribution_counts() -> dict[str, int]:
    return {
        "gt_1m_cells": 0,
        "nodata_adjacent_cells": 0,
        "drain_adjacent_cells": 0,
        "band_edge_adjacent_cells": 0,
        "huc_boundary_or_coastline_proxy_cells": 0,
        "interior_cells": 0,
        "explained_by_any_bucket_cells": 0,
        "unattributed_interior_cells": 0,
        "primary_nodata_adjacent_cells": 0,
        "primary_drain_adjacent_cells": 0,
        "primary_band_edge_adjacent_cells": 0,
        "primary_huc_boundary_or_coastline_proxy_cells": 0,
    }


def make_diff_heatmap(
    *,
    reference_cog: Path,
    candidate_cog: Path,
    output_path: Path,
    threshold_dm: int,
    max_width: int = 900,
) -> None:
    with rasterio.open(reference_cog) as ref, rasterio.open(candidate_cog) as cand:
        scale = max(1, math.ceil(max(ref.width, ref.height) / max_width))
        out_width = math.ceil(ref.width / scale)
        out_height = math.ceil(ref.height / scale)
        image = np.zeros((out_height, out_width, 4), dtype=np.uint8)
        for row_start in range(0, ref.height, scale):
            row_count = min(scale, ref.height - row_start)
            ref_rows = ref.read(1, window=Window(0, row_start, ref.width, row_count))
            cand_rows = cand.read(1, window=Window(0, row_start, cand.width, row_count))
            sampled_ref = ref_rows[0:1, ::scale]
            sampled_cand = cand_rows[0:1, ::scale]
            valid = (sampled_ref != NODATA_U16) & (sampled_cand != NODATA_U16)
            diff = np.abs(sampled_ref.astype(np.int32) - sampled_cand.astype(np.int32))
            exceed = valid & (diff > threshold_dm)
            out_y = row_start // scale
            w = min(exceed.shape[1], out_width)
            image[out_y, :w, 0] = np.where(exceed[0, :w], 239, 40)
            image[out_y, :w, 1] = np.where(exceed[0, :w], 68, 40)
            image[out_y, :w, 2] = np.where(exceed[0, :w], 68, 40)
            image[out_y, :w, 3] = np.where(valid[0, :w], 220, 0)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image, mode="RGBA").save(output_path, optimize=True)


def diff_cogs(
    *,
    huc4: str,
    reference_cog: Path,
    candidate_cog: Path,
    report_root: Path,
    region_id: str,
    sample_count: int,
    seed: int,
    band_rows: int,
    attribution_edge_pixels: int,
    drain_adjacent_dm: int,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    sample_rate = None
    sampled_diffs: list[np.ndarray] = []
    region, geometry_wgs84 = fetch_huc4_shape(huc4)
    polygon_geometry = project_geometry(
        geometry_wgs84, source_crs="EPSG:4326", target_crs="EPSG:5070"
    )
    attribution = empty_attribution_counts()
    counts = {
        "total_cells": 0,
        "valid_pair_cells": 0,
        "reference_valid_cells": 0,
        "candidate_valid_cells": 0,
        "gt_1m_cells": 0,
        "low_reference_cells": 0,
        "low_candidate_cells": 0,
        "low_intersection_cells": 0,
        "low_union_cells": 0,
    }
    with rasterio.open(reference_cog) as ref, rasterio.open(candidate_cog) as cand:
        if ref.width != cand.width or ref.height != cand.height:
            raise RuntimeError("Reference and candidate grids differ.")
        if ref.transform != cand.transform:
            raise RuntimeError("Reference and candidate transforms differ.")
        sample_rate = sample_count / max(1, ref.width * ref.height)
        pixel_m = abs(float(ref.transform.e))
        huc_boundary_buffer = polygon_geometry.boundary.buffer(
            max(pixel_m, pixel_m * attribution_edge_pixels)
        )
        for row_start in range(0, ref.height, 512):
            row_count = min(512, ref.height - row_start)
            padded_row_start = max(0, row_start - 1)
            padded_row_stop = min(ref.height, row_start + row_count + 1)
            padded_window = Window(
                0, padded_row_start, ref.width, padded_row_stop - padded_row_start
            )
            inner_start = row_start - padded_row_start
            inner_stop = inner_start + row_count
            window = Window(0, row_start, ref.width, row_count)
            ref_padded = ref.read(1, window=padded_window)
            cand_padded = cand.read(1, window=padded_window)
            ref_values = ref_padded[inner_start:inner_stop, :]
            cand_values = cand_padded[inner_start:inner_stop, :]
            ref_valid = ref_values != NODATA_U16
            cand_valid = cand_values != NODATA_U16
            valid_pair = ref_valid & cand_valid
            counts["total_cells"] += int(ref_values.size)
            counts["reference_valid_cells"] += int(np.count_nonzero(ref_valid))
            counts["candidate_valid_cells"] += int(np.count_nonzero(cand_valid))
            counts["valid_pair_cells"] += int(np.count_nonzero(valid_pair))
            if np.any(valid_pair):
                diff_dm = np.abs(
                    ref_values[valid_pair].astype(np.int32)
                    - cand_values[valid_pair].astype(np.int32)
                )
                counts["gt_1m_cells"] += int(np.count_nonzero(diff_dm > 10))
                take = rng.random(diff_dm.size) < sample_rate
                if np.any(take):
                    sampled_diffs.append(diff_dm[take].astype(np.uint16))
                diff_gt = np.zeros(ref_values.shape, dtype=bool)
                diff_gt[valid_pair] = diff_dm > DIFF_THRESHOLD_DM
                if np.any(diff_gt):
                    padded_valid = (ref_padded != NODATA_U16) & (
                        cand_padded != NODATA_U16
                    )
                    padded_drain = (
                        (ref_padded != NODATA_U16) & (ref_padded <= drain_adjacent_dm)
                    ) | (
                        (cand_padded != NODATA_U16) & (cand_padded <= drain_adjacent_dm)
                    )
                    nodata_adjacent = neighbor_any(~padded_valid)[
                        inner_start:inner_stop, :
                    ]
                    drain_adjacent = neighbor_any(padded_drain)[
                        inner_start:inner_stop, :
                    ]
                    band_adjacent = band_edge_mask(
                        row_start=row_start,
                        row_count=row_count,
                        height=ref.height,
                        band_rows=band_rows,
                        edge_pixels=attribution_edge_pixels,
                        width=ref.width,
                    )
                    boundary_adjacent = huc_boundary_mask(
                        huc_boundary_buffer=huc_boundary_buffer,
                        window=window,
                        transform=ref.transform,
                        row_count=row_count,
                        width=ref.width,
                    )
                    explained = (
                        nodata_adjacent
                        | drain_adjacent
                        | band_adjacent
                        | boundary_adjacent
                    )
                    attribution["gt_1m_cells"] += int(np.count_nonzero(diff_gt))
                    attribution["nodata_adjacent_cells"] += int(
                        np.count_nonzero(diff_gt & nodata_adjacent)
                    )
                    attribution["drain_adjacent_cells"] += int(
                        np.count_nonzero(diff_gt & drain_adjacent)
                    )
                    attribution["band_edge_adjacent_cells"] += int(
                        np.count_nonzero(diff_gt & band_adjacent)
                    )
                    attribution["huc_boundary_or_coastline_proxy_cells"] += int(
                        np.count_nonzero(diff_gt & boundary_adjacent)
                    )
                    attribution["interior_cells"] += int(
                        np.count_nonzero(diff_gt & ~boundary_adjacent)
                    )
                    attribution["explained_by_any_bucket_cells"] += int(
                        np.count_nonzero(diff_gt & explained)
                    )
                    attribution["unattributed_interior_cells"] += int(
                        np.count_nonzero(diff_gt & ~explained)
                    )
                    remaining = diff_gt.copy()
                    for key, mask in [
                        ("primary_nodata_adjacent_cells", nodata_adjacent),
                        ("primary_drain_adjacent_cells", drain_adjacent),
                        ("primary_band_edge_adjacent_cells", band_adjacent),
                        (
                            "primary_huc_boundary_or_coastline_proxy_cells",
                            boundary_adjacent,
                        ),
                    ]:
                        primary = remaining & mask
                        attribution[key] += int(np.count_nonzero(primary))
                        remaining &= ~mask
            ref_low = ref_valid & (ref_values <= LOW_THRESHOLD_DM)
            cand_low = cand_valid & (cand_values <= LOW_THRESHOLD_DM)
            counts["low_reference_cells"] += int(np.count_nonzero(ref_low))
            counts["low_candidate_cells"] += int(np.count_nonzero(cand_low))
            counts["low_intersection_cells"] += int(
                np.count_nonzero(ref_low & cand_low)
            )
            counts["low_union_cells"] += int(np.count_nonzero(ref_low | cand_low))

    diffs_dm = (
        np.concatenate(sampled_diffs)
        if sampled_diffs
        else np.array([], dtype=np.uint16)
    )
    diffs_m = diffs_dm.astype(np.float32) / 10.0
    low_union = counts["low_union_cells"]
    attribution_pct = {
        key.replace("_cells", "_pct"): round(
            value * 100.0 / attribution["gt_1m_cells"], 3
        )
        if attribution["gt_1m_cells"]
        else None
        for key, value in attribution.items()
    }
    diff_result = {
        "region": asdict(region),
        "reference_cog": str(reference_cog),
        "candidate_cog": str(candidate_cog),
        "sample_seed": seed,
        "sample_target": sample_count,
        "sample_count": int(diffs_dm.size),
        "sample_rate": sample_rate,
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
        "threshold_3ft": {
            "reference_cells": counts["low_reference_cells"],
            "candidate_cells": counts["low_candidate_cells"],
            "intersection_cells": counts["low_intersection_cells"],
            "union_cells": low_union,
            "jaccard": round(counts["low_intersection_cells"] / low_union, 4)
            if low_union
            else None,
        },
        "attribution": {
            "params": {
                "diff_threshold_m": DIFF_THRESHOLD_DM / 10.0,
                "adjacent_pixels": attribution_edge_pixels,
                "drain_adjacent_dm": drain_adjacent_dm,
                "band_rows": band_rows,
                "coastline_proxy": "HUC polygon boundary buffer; separates outer-boundary/coastal-adjacent differences from interior differences.",
            },
            "counts": attribution,
            "percent_of_gt_1m": attribution_pct,
        },
    }
    report_dir = report_root / region_id
    report_dir.mkdir(parents=True, exist_ok=True)
    heatmap_path = report_dir / "diff-gt1m-sample.png"
    make_diff_heatmap(
        reference_cog=reference_cog,
        candidate_cog=candidate_cog,
        output_path=heatmap_path,
        threshold_dm=10,
    )
    diff_result["heatmap"] = str(heatmap_path)
    (report_dir / "diff-metrics.json").write_text(
        json.dumps(diff_result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_diff_report(report_dir, diff_result)
    return diff_result


def write_build_report(report_root: Path, result: dict[str, Any]) -> None:
    report_dir = report_root / result["region_id"]
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "build-metrics.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    build = result["build"]
    checks = {
        "wall_time": build["wall_time_s"] <= DEFAULT_MAX_WALL_S,
        "peak_rss": build["peak_rss_mb"] <= DEFAULT_MAX_RSS_MB,
        "source_cog_size": build["source_cog_bytes"] <= DEFAULT_MAX_SOURCE_COG_BYTES,
    }
    lines = [
        f"# Banded HAND Build: {result['region']['huc4']} {result['region']['name']}",
        "",
        f"- Wall time: `{build['wall_time_s']}s` ({checks['wall_time']}).",
        f"- Peak RSS: `{build['peak_rss_mb']} MB` ({checks['peak_rss']}).",
        f"- Source COG: `{format_bytes(build['source_cog_bytes'])}` ({checks['source_cog_size']}).",
        f"- Bands: `{len(result['bands'])}`; overlap: `{result['params']['overlap_m']}m`; interior rows: `{result['params']['band_rows']}`.",
        f"- Output COG: `{result['source_cog']}`.",
    ]
    (report_dir / "build-summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def write_diff_report(report_dir: Path, diff_result: dict[str, Any]) -> None:
    diff = diff_result["abs_diff_m"]
    threshold = diff_result["threshold_3ft"]
    attribution = diff_result["attribution"]["counts"]
    attribution_pct = diff_result["attribution"]["percent_of_gt_1m"]
    lines = [
        "# Banded vs Monolithic HAND Diff",
        "",
        f"- Samples: `{diff_result['sample_count']}`.",
        f"- Abs diff p50/p95/p99/max sampled: `{diff['p50']}` / `{diff['p95']}` / `{diff['p99']}` / `{diff['max_sampled']}` m.",
        f"- Within 1m: `{diff['within_1m_pct']}%`.",
        f"- Cells with >1m diff: `{diff_result['counts']['gt_1m_cells']}`.",
        f"- 3ft threshold Jaccard: `{threshold['jaccard']}`.",
        f"- >1m attribution: nodata-adjacent `{attribution['nodata_adjacent_cells']}` ({attribution_pct['nodata_adjacent_pct']}%), drain-adjacent `{attribution['drain_adjacent_cells']}` ({attribution_pct['drain_adjacent_pct']}%), band-edge-adjacent `{attribution['band_edge_adjacent_cells']}` ({attribution_pct['band_edge_adjacent_pct']}%), HUC-boundary/coastline-proxy `{attribution['huc_boundary_or_coastline_proxy_cells']}` ({attribution_pct['huc_boundary_or_coastline_proxy_pct']}%), unattributed interior `{attribution['unattributed_interior_cells']}` ({attribution_pct['unattributed_interior_pct']}%).",
        f"- Heatmap: `{diff_result['heatmap']}`.",
    ]
    (report_dir / "diff-summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--huc4", default=DEFAULT_HUC4)
        subparser.add_argument(
            "--reference-cog",
            type=Path,
            default=Path(
                "/mnt/storage/floodmap/data/terrain/hand/huc4-0107-merrimack-buffer5km-clipped.tif"
            ),
        )
        subparser.add_argument(
            "--data-root",
            type=Path,
            default=Path(os.getenv("FLOODMAP_DATA_ROOT", "data")),
        )
        subparser.add_argument("--artifact-root", type=Path, default=Path("scratch"))
        subparser.add_argument(
            "--report-root", type=Path, default=Path("docs/qa/hand-banded")
        )
        subparser.add_argument(
            "--buffer-km", type=float, default=DEFAULT_BOUNDARY_BUFFER_KM
        )
        subparser.add_argument("--overlap-m", type=float, default=DEFAULT_OVERLAP_M)
        subparser.add_argument("--band-rows", type=int, default=DEFAULT_BAND_ROWS)
        subparser.add_argument(
            "--dem-resolution-m", type=int, default=DEFAULT_DEM_RESOLUTION_M
        )
        subparser.add_argument(
            "--stream-burn-depth-m", type=float, default=DEFAULT_STREAM_BURN_DEPTH_M
        )
        subparser.add_argument(
            "--flow-accumulation-drain-threshold-km2",
            type=float,
            default=DEFAULT_ACCUMULATION_THRESHOLD_KM2,
        )

    build_parser = subparsers.add_parser("build")
    add_common(build_parser)

    diff_parser = subparsers.add_parser("diff")
    add_common(diff_parser)
    diff_parser.add_argument("--candidate-cog", type=Path, required=True)
    diff_parser.add_argument("--region-id", required=True)
    diff_parser.add_argument("--sample-count", type=int, default=DEFAULT_SAMPLE_COUNT)
    diff_parser.add_argument("--seed", type=int, default=7)
    diff_parser.add_argument(
        "--attribution-edge-pixels",
        type=int,
        default=DEFAULT_ATTRIBUTION_EDGE_PIXELS,
    )
    diff_parser.add_argument(
        "--drain-adjacent-dm", type=int, default=DEFAULT_DRAIN_ADJACENT_DM
    )

    run_parser = subparsers.add_parser("run")
    add_common(run_parser)
    run_parser.add_argument("--sample-count", type=int, default=DEFAULT_SAMPLE_COUNT)
    run_parser.add_argument("--seed", type=int, default=7)
    run_parser.add_argument(
        "--attribution-edge-pixels",
        type=int,
        default=DEFAULT_ATTRIBUTION_EDGE_PIXELS,
    )
    run_parser.add_argument(
        "--drain-adjacent-dm", type=int, default=DEFAULT_DRAIN_ADJACENT_DM
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "build":
        result = run_banded_build(
            huc4=args.huc4,
            reference_cog=args.reference_cog,
            data_root=args.data_root,
            artifact_root=args.artifact_root,
            report_root=args.report_root,
            buffer_km=args.buffer_km,
            overlap_m=args.overlap_m,
            band_rows=args.band_rows,
            dem_resolution_m=args.dem_resolution_m,
            stream_burn_depth_m=args.stream_burn_depth_m,
            accumulation_threshold_km2=args.flow_accumulation_drain_threshold_km2,
        )
        print(json.dumps(result["build"], indent=2, sort_keys=True))
    elif args.command == "diff":
        result = diff_cogs(
            huc4=args.huc4,
            reference_cog=args.reference_cog,
            candidate_cog=args.candidate_cog,
            report_root=args.report_root,
            region_id=args.region_id,
            sample_count=args.sample_count,
            seed=args.seed,
            band_rows=args.band_rows,
            attribution_edge_pixels=args.attribution_edge_pixels,
            drain_adjacent_dm=args.drain_adjacent_dm,
        )
        print(json.dumps(result["abs_diff_m"], indent=2, sort_keys=True))
    elif args.command == "run":
        build = run_banded_build(
            huc4=args.huc4,
            reference_cog=args.reference_cog,
            data_root=args.data_root,
            artifact_root=args.artifact_root,
            report_root=args.report_root,
            buffer_km=args.buffer_km,
            overlap_m=args.overlap_m,
            band_rows=args.band_rows,
            dem_resolution_m=args.dem_resolution_m,
            stream_burn_depth_m=args.stream_burn_depth_m,
            accumulation_threshold_km2=args.flow_accumulation_drain_threshold_km2,
        )
        diff = diff_cogs(
            huc4=args.huc4,
            reference_cog=args.reference_cog,
            candidate_cog=Path(build["source_cog"]),
            report_root=args.report_root,
            region_id=build["region_id"],
            sample_count=args.sample_count,
            seed=args.seed,
            band_rows=args.band_rows,
            attribution_edge_pixels=args.attribution_edge_pixels,
            drain_adjacent_dm=args.drain_adjacent_dm,
        )
        print(
            json.dumps({"build": build["build"], "diff": diff["abs_diff_m"]}, indent=2)
        )


if __name__ == "__main__":
    main()
