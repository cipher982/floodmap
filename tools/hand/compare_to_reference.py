#!/usr/bin/env python3
"""Compare HAND threshold masks against FEMA NFHL flood hazard polygons.

This produces agent-reviewable validation artifacts:

- `metrics.json` with overlap/confusion metrics per threshold.
- `summary.md` with a compact human-readable readout.
- `comparison-<N>ft.png` panels: HAND, FEMA, and overlap/difference on the
  exact same raster grid.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import numpy as np

FEMA_NFHL_FLOOD_HAZARD_ZONES_QUERY_URL = (
    "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
)
FEMA_SFHA_FILTER = "SFHA_TF = 'T'"
DEFAULT_THRESHOLDS_FT = (1.0, 3.0, 6.0, 10.0, 20.0)
U16_NODATA = 65535


@dataclass(frozen=True)
class HandRegion:
    id: str
    bbox: tuple[float, float, float, float]
    url: Path
    crs: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare HAND COGs against FEMA NFHL SFHA polygons."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Terrain manifest path. Defaults to $TERRAIN_MANIFEST_PATH or data root.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(os.getenv("FLOODMAP_DATA_ROOT", "data")),
        help="Floodmap data root for default manifest/cache paths.",
    )
    parser.add_argument(
        "--region",
        action="append",
        help="Region id to compare. Repeatable. Defaults to all HAND regions.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/qa/hand-reference"),
        help="Directory for validation reports.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Cache directory for fetched FEMA features.",
    )
    parser.add_argument(
        "--threshold-ft",
        type=float,
        action="append",
        default=None,
        help="HAND threshold in feet. Repeatable. Defaults to 1, 3, 6, 10, and 20 ft.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=100,
        help="FEMA object id fetch chunk size.",
    )
    parser.add_argument(
        "--simplify-m",
        type=float,
        default=5.0,
        help="ArcGIS maxAllowableOffset in the HAND raster CRS units.",
    )
    parser.add_argument(
        "--all-touched",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Rasterize FEMA polygons with all touched cells included.",
    )
    parser.add_argument(
        "--max-image-dim",
        type=int,
        default=1800,
        help="Maximum output PNG width/height for each panel image.",
    )
    parser.add_argument(
        "--baseline-raster",
        type=Path,
        default=None,
        help="Optional absolute-elevation raster for same-coverage lowland baseline.",
    )
    return parser.parse_args()


def default_manifest_path(data_root: Path) -> Path:
    if env_path := os.getenv("TERRAIN_MANIFEST_PATH"):
        return Path(env_path)
    return data_root / "terrain" / "manifest.json"


def load_regions(manifest_path: Path) -> tuple[str, list[HandRegion]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hand_layer = manifest.get("layers", {}).get("hand", {})
    regions = [
        HandRegion(
            id=str(region["id"]),
            bbox=tuple(float(v) for v in region["bbox"]),
            url=local_manifest_path(str(region["url"])),
            crs=str(region.get("crs", "EPSG:5070")),
        )
        for region in hand_layer.get("regions", [])
    ]
    return str(manifest["dataset_version"]), regions


def local_manifest_path(value: str) -> Path:
    parsed = urlparse(value)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    if parsed.scheme:
        raise ValueError(f"Only local HAND COG paths are supported, got {value!r}")
    return Path(value)


def signed_ring_area(ring: list[list[float]]) -> float:
    area = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
        area += x1 * y2 - x2 * y1
    return area / 2.0


def esri_polygon_to_shape(geometry: dict[str, Any]):
    from shapely.geometry import MultiPolygon, Polygon
    from shapely.validation import make_valid

    rings = geometry.get("rings") or []
    if not rings:
        return None

    outers: list[list[list[float]]] = []
    holes: list[list[list[float]]] = []
    for ring in rings:
        if len(ring) < 4:
            continue
        # ArcGIS polygon exteriors are clockwise in these responses.
        if signed_ring_area(ring) < 0:
            outers.append(ring)
        else:
            holes.append(ring)

    if not outers:
        outers = rings
        holes = []

    polygons: list[Any] = []
    pending_holes = [(ring, Polygon(ring)) for ring in holes]
    for outer in outers:
        outer_polygon = Polygon(outer)
        assigned_holes: list[list[list[float]]] = []
        remaining_holes = []
        for hole_ring, hole_polygon in pending_holes:
            point = hole_polygon.representative_point()
            if outer_polygon.contains(point):
                assigned_holes.append(hole_ring)
            else:
                remaining_holes.append((hole_ring, hole_polygon))
        pending_holes = remaining_holes
        polygon = Polygon(outer, assigned_holes)
        if not polygon.is_valid:
            polygon = make_valid(polygon)
        if not polygon.is_empty:
            if polygon.geom_type == "Polygon":
                polygons.append(polygon)
            elif polygon.geom_type == "MultiPolygon":
                polygons.extend(list(polygon.geoms))

    if not polygons:
        return None
    if len(polygons) == 1:
        return polygons[0]
    return MultiPolygon(polygons)


def cache_path_for_region(
    cache_dir: Path, region: HandRegion, epsg: int, simplify_m: float
) -> Path:
    simplify_tag = f"{simplify_m:g}".replace(".", "p").replace("-", "m")
    return cache_dir / (
        f"{region.id}-fema-sfha-epsg{epsg}-offset{simplify_tag}m.json.gz"
    )


def arcgis_generalization_params(
    *, target_epsg: int, simplify_m: float
) -> dict[str, Any]:
    import rasterio

    crs = rasterio.crs.CRS.from_epsg(target_epsg)
    if crs.is_geographic:
        return {
            "max_allowable_offset": simplify_m / 111_320.0,
            "offset_units": "degrees",
            "geometry_precision": 6,
            "source_simplify_m": simplify_m,
        }
    return {
        "max_allowable_offset": simplify_m,
        "offset_units": "crs_units",
        "geometry_precision": 2,
        "source_simplify_m": simplify_m,
    }


def request_json(
    session: Any,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    retries: int = 4,
    timeout: int = 120,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.request(
                method,
                url,
                params=params,
                data=data,
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise RuntimeError(payload["error"])
            return payload
        except Exception as exc:  # pragma: no cover - network variability
            last_error = exc
            if attempt == retries - 1:
                break
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"FEMA request failed: {last_error}") from last_error


def fetch_fema_sfha_features(
    *,
    region: HandRegion,
    target_epsg: int,
    cache_dir: Path,
    chunk_size: int,
    simplify_m: float,
) -> list[dict[str, Any]]:
    cache_path = cache_path_for_region(cache_dir, region, target_epsg, simplify_m)
    generalization = arcgis_generalization_params(
        target_epsg=target_epsg, simplify_m=simplify_m
    )
    if cache_path.exists():
        with gzip.open(cache_path, "rt", encoding="utf-8") as fh:
            cached = json.load(fh)
        validate_spatial_reference(cached.get("spatial_reference"), target_epsg)
        if cached.get("where") != FEMA_SFHA_FILTER:
            raise ValueError(f"FEMA cache filter mismatch in {cache_path}")
        if cached.get("simplify_m") != simplify_m:
            raise ValueError(f"FEMA cache simplify_m mismatch in {cache_path}")
        if cached.get("max_allowable_offset") != generalization["max_allowable_offset"]:
            raise ValueError(f"FEMA cache maxAllowableOffset mismatch in {cache_path}")
        return cached["features"]

    west, south, east, north = region.bbox
    import requests

    session = requests.Session()
    session.headers.update({"User-Agent": "Floodmap HAND validation"})

    id_payload = request_json(
        session,
        "GET",
        FEMA_NFHL_FLOOD_HAZARD_ZONES_QUERY_URL,
        params={
            "f": "json",
            "where": FEMA_SFHA_FILTER,
            "returnIdsOnly": "true",
            "geometry": f"{west},{south},{east},{north}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
        },
    )
    object_ids = id_payload.get("objectIds") or []
    object_ids = sorted(int(object_id) for object_id in object_ids)

    features: list[dict[str, Any]] = []
    total_chunks = max(1, math.ceil(len(object_ids) / chunk_size))
    for index in range(0, len(object_ids), chunk_size):
        chunk = object_ids[index : index + chunk_size]
        chunk_number = index // chunk_size + 1
        print(
            f"Fetching FEMA {region.id}: chunk {chunk_number}/{total_chunks} "
            f"({len(chunk)} object ids)",
            file=sys.stderr,
        )
        payload = request_json(
            session,
            "POST",
            FEMA_NFHL_FLOOD_HAZARD_ZONES_QUERY_URL,
            data={
                "f": "json",
                "objectIds": ",".join(str(object_id) for object_id in chunk),
                "outFields": "OBJECTID,FLD_ZONE,SFHA_TF,ZONE_SUBTY",
                "returnGeometry": "true",
                "outSR": target_epsg,
                "maxAllowableOffset": generalization["max_allowable_offset"],
                "geometryPrecision": generalization["geometry_precision"],
            },
        )
        validate_spatial_reference(payload.get("spatialReference"), target_epsg)
        features.extend(payload.get("features") or [])

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(cache_path, "wt", encoding="utf-8") as fh:
        json.dump(
            {
                "source": FEMA_NFHL_FLOOD_HAZARD_ZONES_QUERY_URL,
                "where": FEMA_SFHA_FILTER,
                "target_epsg": target_epsg,
                "spatial_reference": {"wkid": target_epsg},
                "simplify_m": simplify_m,
                "max_allowable_offset": generalization["max_allowable_offset"],
                "offset_units": generalization["offset_units"],
                "geometry_precision": generalization["geometry_precision"],
                "feature_count": len(features),
                "features": features,
            },
            fh,
        )
    return features


def validate_spatial_reference(
    spatial_reference: dict[str, Any] | None, target_epsg: int
) -> None:
    if not spatial_reference:
        return
    wkids = {
        int(value)
        for key in ("wkid", "latestWkid")
        if (value := spatial_reference.get(key)) is not None
    }
    if wkids and target_epsg not in wkids:
        raise ValueError(
            f"FEMA response CRS mismatch: expected EPSG:{target_epsg}, "
            f"got {spatial_reference}"
        )


def rasterize_fema_mask(
    *,
    features: list[dict[str, Any]],
    out_shape: tuple[int, int],
    transform,
    all_touched: bool,
) -> np.ndarray:
    from rasterio.features import rasterize
    from shapely.geometry import mapping

    shapes = []
    invalid_count = 0
    for feature in features:
        geom = esri_polygon_to_shape(feature.get("geometry") or {})
        if geom is None or geom.is_empty:
            invalid_count += 1
            continue
        shapes.append((mapping(geom), 1))

    if invalid_count:
        print(f"Skipped {invalid_count} empty/invalid FEMA geometries", file=sys.stderr)
    if not shapes:
        return np.zeros(out_shape, dtype=np.bool_)
    mask = rasterize(
        shapes,
        out_shape=out_shape,
        transform=transform,
        fill=0,
        dtype="uint8",
        all_touched=all_touched,
    )
    return mask.astype(np.bool_)


def compute_metrics(
    *,
    hand_values: np.ndarray,
    fema_mask: np.ndarray,
    thresholds_ft: list[float],
    baseline_values: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    valid = hand_values != U16_NODATA
    valid_count = int(valid.sum())
    fema_valid = fema_mask & valid
    fema_count = int(fema_valid.sum())
    hand_float = hand_values.astype(np.float32)
    baseline_valid = (
        np.isfinite(baseline_values) & valid if baseline_values is not None else None
    )
    metrics = []
    for threshold_ft in thresholds_ft:
        threshold_m = threshold_ft * 0.3048
        threshold_dm = threshold_m * 10.0
        hand_mask = (hand_float <= threshold_dm) & valid
        tp = int((hand_mask & fema_valid).sum())
        fp = int((hand_mask & ~fema_valid & valid).sum())
        fn = int((~hand_mask & fema_valid).sum())
        tn = int((~hand_mask & ~fema_valid & valid).sum())
        union = tp + fp + fn
        hand_count = int(hand_mask.sum())
        expected_random_tp = (
            hand_count * fema_count / valid_count if valid_count else None
        )
        expected_random_union = (
            hand_count + fema_count - expected_random_tp
            if expected_random_tp is not None
            else None
        )
        expected_random_iou = (
            expected_random_tp / expected_random_union
            if expected_random_tp is not None
            and expected_random_tp > 0
            and expected_random_union is not None
            and expected_random_union > 0
            else None
        )
        expected_random_precision = (
            fema_count / valid_count if hand_count > 0 and valid_count > 0 else None
        )
        iou = tp / union if union else None
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        baseline = same_coverage_baseline_metrics(
            baseline_values=baseline_values,
            baseline_valid=baseline_valid,
            fema_valid=fema_valid,
            valid_count=valid_count,
            target_cell_count=hand_count,
        )
        metrics.append(
            {
                "threshold_ft": threshold_ft,
                "threshold_m": threshold_m,
                "valid_cells": valid_count,
                "fema_cells": fema_count,
                "hand_cells": hand_count,
                "true_positive": tp,
                "false_positive_hand_only": fp,
                "false_negative_fema_only": fn,
                "true_negative": tn,
                "iou": iou,
                "precision": precision,
                "recall": recall,
                "hand_coverage_pct": hand_count / valid_count * 100
                if valid_count
                else None,
                "fema_coverage_pct": fema_count / valid_count * 100
                if valid_count
                else None,
                "overlap_pct_of_fema": tp / fema_count * 100 if fema_count else None,
                "overlap_pct_of_hand": tp / hand_count * 100 if hand_count else None,
                "expected_random_true_positive": expected_random_tp,
                "expected_random_iou": expected_random_iou,
                "expected_random_precision": expected_random_precision,
                "precision_lift_vs_random": precision / expected_random_precision
                if precision is not None
                and expected_random_precision is not None
                and expected_random_precision > 0
                else None,
                "iou_lift_vs_random": iou / expected_random_iou
                if iou is not None
                and expected_random_iou is not None
                and expected_random_iou > 0
                else None,
                "low_elevation_baseline": baseline,
                "precision_lift_vs_low_elevation": precision / baseline["precision"]
                if precision is not None
                and baseline["precision"] is not None
                and baseline["precision"] > 0
                else None,
                "iou_lift_vs_low_elevation": iou / baseline["iou"]
                if iou is not None
                and baseline["iou"] is not None
                and baseline["iou"] > 0
                else None,
            }
        )
    return metrics


def same_coverage_baseline_metrics(
    *,
    baseline_values: np.ndarray | None,
    baseline_valid: np.ndarray | None,
    fema_valid: np.ndarray,
    valid_count: int,
    target_cell_count: int,
) -> dict[str, Any]:
    empty = {
        "enabled": False,
        "cells": None,
        "cutoff": None,
        "precision": None,
        "recall": None,
        "iou": None,
        "coverage_pct": None,
    }
    if (
        baseline_values is None
        or baseline_valid is None
        or valid_count == 0
        or target_cell_count == 0
    ):
        return empty

    candidate_values = baseline_values[baseline_valid]
    if candidate_values.size == 0:
        return empty

    rank = min(target_cell_count, candidate_values.size)
    cutoff = float(np.partition(candidate_values, rank - 1)[rank - 1])
    baseline_mask = baseline_valid & (baseline_values <= cutoff)
    baseline_cells = int(baseline_mask.sum())
    tp = int((baseline_mask & fema_valid).sum())
    fp = int((baseline_mask & ~fema_valid).sum())
    fn = int((~baseline_mask & fema_valid).sum())
    union = tp + fp + fn
    return {
        "enabled": True,
        "cells": baseline_cells,
        "cutoff": cutoff,
        "precision": tp / (tp + fp) if (tp + fp) else None,
        "recall": tp / (tp + fn) if (tp + fn) else None,
        "iou": tp / union if union else None,
        "coverage_pct": baseline_cells / valid_count * 100,
    }


def read_baseline_raster(
    *,
    path: Path,
    out_shape: tuple[int, int],
    dst_transform: Any,
    dst_crs: Any,
) -> np.ndarray:
    import rasterio
    from rasterio.warp import Resampling, reproject

    baseline = np.full(out_shape, np.nan, dtype=np.float32)
    with rasterio.open(path) as src:
        nodata = src.nodata
        same_grid = (
            src.shape == out_shape
            and src.transform == dst_transform
            and src.crs == dst_crs
        )
        if same_grid:
            baseline = src.read(1).astype(np.float32)
        else:
            reproject(
                source=rasterio.band(src, 1),
                destination=baseline,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=nodata,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )
    if nodata is not None and np.isfinite(nodata):
        baseline[baseline == nodata] = np.nan
    baseline[~np.isfinite(baseline)] = np.nan
    return baseline


def downsample_mask(mask: np.ndarray, max_dim: int):
    from PIL import Image

    height, width = mask.shape
    scale = max(width / max_dim, height / max_dim, 1.0)
    out_size = (max(1, int(width / scale)), max(1, int(height / scale)))
    image = Image.fromarray(mask.astype(np.uint8) * 255)
    if image.size != out_size:
        image = image.resize(out_size, Image.Resampling.NEAREST)
    return image


def mask_panel(
    *,
    valid: np.ndarray,
    hand_mask: np.ndarray,
    fema_mask: np.ndarray,
    mode: str,
    max_dim: int,
) -> Any:
    from PIL import Image

    valid_img = np.array(downsample_mask(valid, max_dim)) > 0
    hand_img = np.array(downsample_mask(hand_mask, max_dim)) > 0
    fema_img = np.array(downsample_mask(fema_mask, max_dim)) > 0
    h, w = valid_img.shape
    rgb = np.full((h, w, 3), 246, dtype=np.uint8)
    rgb[~valid_img] = (220, 220, 220)

    if mode == "hand":
        rgb[hand_img & valid_img] = (33, 150, 243)
    elif mode == "fema":
        rgb[fema_img & valid_img] = (136, 86, 167)
    elif mode == "diff":
        overlap = hand_img & fema_img & valid_img
        hand_only = hand_img & ~fema_img & valid_img
        fema_only = ~hand_img & fema_img & valid_img
        rgb[hand_only] = (33, 150, 243)
        rgb[fema_only] = (214, 80, 118)
        rgb[overlap] = (54, 170, 95)
    else:
        raise ValueError(f"Unknown panel mode: {mode}")
    return Image.fromarray(rgb)


def labeled_panel(image: Any, title: str, subtitle: str) -> Any:
    from PIL import Image, ImageDraw, ImageFont

    label_height = 54
    panel = Image.new("RGB", (image.width, image.height + label_height), "white")
    panel.paste(image, (0, label_height))
    draw = ImageDraw.Draw(panel)
    font = ImageFont.load_default()
    draw.text((12, 10), title, fill=(30, 41, 59), font=font)
    draw.text((12, 30), subtitle, fill=(71, 85, 105), font=font)
    return panel


def write_comparison_images(
    *,
    output_dir: Path,
    region_id: str,
    hand_values: np.ndarray,
    fema_mask: np.ndarray,
    thresholds_ft: list[float],
    max_dim: int,
) -> dict[str, str]:
    from PIL import Image

    output_paths: dict[str, str] = {}
    valid = hand_values != U16_NODATA
    for threshold_ft in thresholds_ft:
        threshold_dm = threshold_ft * 0.3048 * 10.0
        hand_mask = (hand_values.astype(np.float32) <= threshold_dm) & valid
        threshold_label = f"{threshold_ft:g}ft"
        panels = [
            labeled_panel(
                mask_panel(
                    valid=valid,
                    hand_mask=hand_mask,
                    fema_mask=fema_mask,
                    mode="hand",
                    max_dim=max_dim,
                ),
                f"HAND <= {threshold_label}",
                "Blue = land within threshold above drainage",
            ),
            labeled_panel(
                mask_panel(
                    valid=valid,
                    hand_mask=hand_mask,
                    fema_mask=fema_mask,
                    mode="fema",
                    max_dim=max_dim,
                ),
                "FEMA SFHA",
                "Purple = FEMA 1% annual chance flood hazard",
            ),
            labeled_panel(
                mask_panel(
                    valid=valid,
                    hand_mask=hand_mask,
                    fema_mask=fema_mask,
                    mode="diff",
                    max_dim=max_dim,
                ),
                "Overlap / Difference",
                "Green overlap, blue HAND-only, pink FEMA-only",
            ),
        ]
        combined = Image.new(
            "RGB",
            (
                sum(panel.width for panel in panels),
                max(panel.height for panel in panels),
            ),
            "white",
        )
        x = 0
        for panel in panels:
            combined.paste(panel, (x, 0))
            x += panel.width
        path = output_dir / f"comparison-{threshold_label}.png"
        combined.save(path, optimize=True)
        output_paths[threshold_label] = path.name
    return output_paths


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def fmt_num(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def write_summary(
    *,
    output_dir: Path,
    region: HandRegion,
    dataset_version: str,
    hand_path: Path,
    fema_feature_count: int,
    fema_total_cells: int,
    fema_in_nodata_cells: int,
    all_touched: bool,
    simplify_m: float,
    max_allowable_offset: float,
    offset_units: str,
    baseline_raster: Path | None,
    metrics: list[dict[str, Any]],
    images: dict[str, str],
) -> None:
    lines = [
        f"# HAND vs FEMA NFHL: {region.id}",
        "",
        f"- Terrain manifest version: `{dataset_version}`",
        f"- HAND source: `{hand_path}`",
        f"- FEMA source: `{FEMA_NFHL_FLOOD_HAZARD_ZONES_QUERY_URL}`",
        f"- FEMA filter: `{FEMA_SFHA_FILTER}` (Special Flood Hazard Area, 1% annual chance flood hazard)",
        f"- FEMA feature count fetched: `{fema_feature_count}`",
        f"- FEMA raster cells: `{fema_total_cells}`; in HAND nodata: `{fema_in_nodata_cells}`",
        f"- Rasterization: `all_touched={str(all_touched).lower()}`, "
        f"`maxAllowableOffset={max_allowable_offset:g} {offset_units}` "
        f"(requested ~`{simplify_m:g}m`)",
        f"- Low-elevation baseline raster: `{baseline_raster}`"
        if baseline_raster
        else "- Low-elevation baseline raster: not provided",
        f"- Bbox: `{region.bbox}`",
        "",
        "| HAND threshold | IoU | Precision | Recall | Lift vs random | Lift vs low elev | HAND coverage | FEMA coverage | Image |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in metrics:
        key = f"{row['threshold_ft']:g}ft"
        lines.append(
            "| "
            f"{row['threshold_ft']:g} ft | "
            f"{fmt_num(row['iou'])} | "
            f"{fmt_num(row['precision'])} | "
            f"{fmt_num(row['recall'])} | "
            f"{fmt_num(row['precision_lift_vs_random'])}x | "
            f"{fmt_num(row['precision_lift_vs_low_elevation'])}x | "
            f"{fmt_pct(row['hand_coverage_pct'])} | "
            f"{fmt_pct(row['fema_coverage_pct'])} | "
            f"[{images[key]}]({images[key]}) |"
        )
    lines.extend(
        [
            "",
            "Interpretation notes:",
            "",
            "- `maxAllowableOffset` is requested as meters and converted to CRS units for the FEMA service.",
            "- High precision means HAND-highlighted cells usually fall inside FEMA SFHA.",
            "- High recall means HAND captures most FEMA SFHA cells.",
            "- Precision lift compares HAND to a same-coverage random mask; near 1.0x means the threshold is barely more selective than chance.",
            "- Low-elevation lift, when present, compares HAND to the same number of lowest absolute-elevation cells.",
            "- HAND and FEMA are not expected to match perfectly: FEMA is regulatory floodplain mapping; HAND is a terrain-derived height-above-drainage screen.",
            "- FEMA-negative cells are not proof of no flooding; these metrics compare against mapped effective SFHA polygons only.",
        ]
    )
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def compare_region(
    *,
    region: HandRegion,
    dataset_version: str,
    output_root: Path,
    cache_dir: Path,
    thresholds_ft: list[float],
    chunk_size: int,
    simplify_m: float,
    all_touched: bool,
    max_image_dim: int,
    baseline_raster: Path | None,
) -> dict[str, Any]:
    hand_path = region.url
    if not hand_path.exists():
        raise FileNotFoundError(f"HAND COG missing for {region.id}: {hand_path}")

    import rasterio

    with rasterio.open(hand_path) as ds:
        hand_values = ds.read(1)
        target_epsg = ds.crs.to_epsg()
        if target_epsg is None:
            raise ValueError(f"Could not determine EPSG code for {hand_path}: {ds.crs}")
        transform = ds.transform
        crs = ds.crs
        out_shape = (ds.height, ds.width)
        raster_bounds = tuple(float(v) for v in ds.bounds)
    baseline_values = (
        read_baseline_raster(
            path=baseline_raster,
            out_shape=out_shape,
            dst_transform=transform,
            dst_crs=crs,
        )
        if baseline_raster is not None
        else None
    )

    features = fetch_fema_sfha_features(
        region=region,
        target_epsg=target_epsg,
        cache_dir=cache_dir,
        chunk_size=chunk_size,
        simplify_m=simplify_m,
    )
    generalization = arcgis_generalization_params(
        target_epsg=target_epsg, simplify_m=simplify_m
    )
    fema_mask = rasterize_fema_mask(
        features=features,
        out_shape=out_shape,
        transform=transform,
        all_touched=all_touched,
    )
    metrics = compute_metrics(
        hand_values=hand_values,
        fema_mask=fema_mask,
        thresholds_ft=thresholds_ft,
        baseline_values=baseline_values,
    )
    valid = hand_values != U16_NODATA
    fema_total_cells = int(fema_mask.sum())
    fema_in_nodata_cells = int((fema_mask & ~valid).sum())

    output_dir = output_root / region.id
    output_dir.mkdir(parents=True, exist_ok=True)
    images = write_comparison_images(
        output_dir=output_dir,
        region_id=region.id,
        hand_values=hand_values,
        fema_mask=fema_mask,
        thresholds_ft=thresholds_ft,
        max_dim=max_image_dim,
    )

    report = {
        "region_id": region.id,
        "dataset_version": dataset_version,
        "hand_path": str(hand_path),
        "bbox_lonlat": region.bbox,
        "raster_bounds": raster_bounds,
        "raster_shape": {"height": int(out_shape[0]), "width": int(out_shape[1])},
        "raster_crs_epsg": target_epsg,
        "fema_source": FEMA_NFHL_FLOOD_HAZARD_ZONES_QUERY_URL,
        "fema_filter": "SFHA_TF = 'T'",
        "fema_feature_count": len(features),
        "fema_total_cells": fema_total_cells,
        "fema_in_hand_nodata_cells": fema_in_nodata_cells,
        "fema_in_hand_nodata_pct": fema_in_nodata_cells / fema_total_cells * 100
        if fema_total_cells
        else None,
        "all_touched": all_touched,
        "simplify_m": simplify_m,
        "max_allowable_offset": generalization["max_allowable_offset"],
        "offset_units": generalization["offset_units"],
        "geometry_precision": generalization["geometry_precision"],
        "baseline_raster": str(baseline_raster) if baseline_raster else None,
        "thresholds": metrics,
        "images": images,
    }
    (output_dir / "metrics.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_summary(
        output_dir=output_dir,
        region=region,
        dataset_version=dataset_version,
        hand_path=hand_path,
        fema_feature_count=len(features),
        fema_total_cells=fema_total_cells,
        fema_in_nodata_cells=fema_in_nodata_cells,
        all_touched=all_touched,
        simplify_m=simplify_m,
        max_allowable_offset=generalization["max_allowable_offset"],
        offset_units=generalization["offset_units"],
        baseline_raster=baseline_raster,
        metrics=metrics,
        images=images,
    )
    return report


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest or default_manifest_path(args.data_root)
    cache_dir = args.cache_dir or args.data_root / "reference" / "fema-nfhl"
    thresholds_ft = args.threshold_ft or list(DEFAULT_THRESHOLDS_FT)

    dataset_version, regions = load_regions(manifest_path)
    if args.region:
        selected = set(args.region)
        regions = [region for region in regions if region.id in selected]
        missing = selected - {region.id for region in regions}
        if missing:
            raise SystemExit(f"Unknown region(s): {', '.join(sorted(missing))}")
    if not regions:
        raise SystemExit("No HAND regions selected")

    reports = []
    for region in regions:
        print(f"Comparing {region.id}", file=sys.stderr)
        reports.append(
            compare_region(
                region=region,
                dataset_version=dataset_version,
                output_root=args.output_dir,
                cache_dir=cache_dir,
                thresholds_ft=thresholds_ft,
                chunk_size=args.chunk_size,
                simplify_m=args.simplify_m,
                all_touched=args.all_touched,
                max_image_dim=args.max_image_dim,
                baseline_raster=args.baseline_raster,
            )
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "index.json").write_text(
        json.dumps(
            {
                "dataset_version": dataset_version,
                "region_count": len(reports),
                "regions": [
                    {
                        "region_id": report["region_id"],
                        "summary": f"{report['region_id']}/summary.md",
                        "metrics": f"{report['region_id']}/metrics.json",
                    }
                    for report in reports
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
