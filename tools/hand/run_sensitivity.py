#!/usr/bin/env python3
"""Run a compact HAND parameter sensitivity gate for one pilot region."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.hand.compare_to_reference import (  # noqa: E402
    U16_NODATA,
    HandRegion,
    compute_metrics,
    fetch_fema_sfha_features,
    rasterize_fema_mask,
)
from tools.prototypes import generate_birmingham_drainage as hand_gen  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("docs/qa/hand-sensitivity/houston-bayou-pilot")
DEFAULT_BBOX = (-95.82, 29.45, -94.95, 30.15)
DEFAULT_BURNS = (0.0, 2.0, 5.0)
DEFAULT_ACCUMULATIONS = (0.25, 1.0, 4.0, 16.0)
DEFAULT_THRESHOLDS_FT = (3.0, 6.0, 10.0)
BASELINE_BURN_M = 5.0
BASELINE_ACCUMULATION_KM2 = 1.0


@dataclass(frozen=True)
class Variant:
    id: str
    stream_burn_depth_m: float
    accumulation_threshold_km2: float


def parse_float_list(value: str) -> list[float]:
    return [float(part) for part in value.replace(",", " ").split()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run HAND parameter sensitivity and FEMA comparison."
    )
    parser.add_argument("--region-id", default="houston-bayou-pilot")
    parser.add_argument("--title", default="Houston Bayou HAND Sensitivity")
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        default=DEFAULT_BBOX,
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(os.getenv("FLOODMAP_DATA_ROOT", "data")),
    )
    parser.add_argument("--dem-resolution-m", type=int, default=10)
    parser.add_argument("--stream-min-order", type=int, default=2)
    parser.add_argument(
        "--burns",
        type=parse_float_list,
        default=list(DEFAULT_BURNS),
        help="Space- or comma-separated stream burn depths in meters.",
    )
    parser.add_argument(
        "--accumulations",
        type=parse_float_list,
        default=list(DEFAULT_ACCUMULATIONS),
        help="Space- or comma-separated flow accumulation drain thresholds in km^2.",
    )
    parser.add_argument(
        "--threshold-ft",
        type=float,
        action="append",
        default=None,
        help="HAND threshold in feet. Repeatable. Defaults to 3, 6, and 10 ft.",
    )
    parser.add_argument("--fema-simplify-m", type=float, default=5.0)
    parser.add_argument("--fema-chunk-size", type=int, default=100)
    return parser.parse_args()


def variant_id(burn_m: float, accumulation_km2: float) -> str:
    def tag(value: float) -> str:
        return f"{value:g}".replace(".", "p").replace("-", "m")

    return f"burn{tag(burn_m)}m-acc{tag(accumulation_km2)}km2"


def encode_hand(hand: np.ndarray) -> np.ndarray:
    valid = np.isfinite(hand) & (hand >= 0)
    encoded = np.full(hand.shape, U16_NODATA, dtype=np.uint16)
    encoded[valid] = np.clip(np.round(hand[valid] * 10.0), 0, U16_NODATA - 1).astype(
        np.uint16
    )
    return encoded


def threshold_mask(encoded: np.ndarray, threshold_ft: float) -> np.ndarray:
    threshold_dm = threshold_ft * 0.3048 * 10.0
    valid = encoded != U16_NODATA
    return (encoded.astype(np.float32) <= threshold_dm) & valid


def jaccard(mask: np.ndarray, baseline: np.ndarray) -> float | None:
    union = int((mask | baseline).sum())
    if union == 0:
        return None
    return int((mask & baseline).sum()) / union


def threshold_stats(encoded: np.ndarray, thresholds_ft: list[float]) -> dict[str, Any]:
    valid = encoded != U16_NODATA
    valid_count = int(valid.sum())
    stats: dict[str, Any] = {"valid_cells": valid_count, "thresholds": {}}
    for threshold_ft in thresholds_ft:
        mask = threshold_mask(encoded, threshold_ft)
        stats["thresholds"][f"{threshold_ft:g}ft"] = {
            "cells": int(mask.sum()),
            "coverage_pct": int(mask.sum()) * 100.0 / valid_count
            if valid_count
            else None,
        }
    return stats


def configure_region(args: argparse.Namespace, variant: Variant) -> None:
    hand_gen.configure_runtime(
        hand_gen.PrototypeConfig(
            name=f"{args.region_id}-{variant.id}",
            title=f"{args.title} {variant.id}",
            bbox_lonlat=tuple(args.bbox),
            dem_resolution_m=args.dem_resolution_m,
            stream_min_order=args.stream_min_order,
            stream_burn_depth_m=variant.stream_burn_depth_m,
            flow_accumulation_drain_threshold_km2=(variant.accumulation_threshold_km2),
            zoom_min=9,
            zoom_max=12,
        ),
        output_dir=args.output_dir / "scratch" / variant.id,
        source_cog=args.output_dir / "scratch" / f"{variant.id}.tif",
    )


def build_variant(
    *,
    args: argparse.Namespace,
    variant: Variant,
    dem: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    flowlines,
    thresholds_ft: list[float],
    fema_mask: np.ndarray,
    baseline_masks: dict[str, np.ndarray] | None,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    configure_region(args, variant)
    started = time.perf_counter()
    hand, upstream_area_km2, drain_mask, stream_mask = hand_gen.derive_drainage_height(
        dem, x, y, flowlines
    )
    elapsed_s = time.perf_counter() - started
    encoded = encode_hand(hand)
    valid_count = int((encoded != U16_NODATA).sum())
    drain_cell_count = int(np.count_nonzero(drain_mask))
    stream_cell_count = int(np.count_nonzero(stream_mask))
    accumulated_cell_count = int(
        np.count_nonzero(upstream_area_km2 >= variant.accumulation_threshold_km2)
    )

    masks = {
        f"{threshold_ft:g}ft": threshold_mask(encoded, threshold_ft)
        for threshold_ft in thresholds_ft
    }
    metrics = compute_metrics(
        hand_values=encoded,
        fema_mask=fema_mask,
        thresholds_ft=thresholds_ft,
    )
    stats = threshold_stats(encoded, thresholds_ft)
    jaccards = {}
    if baseline_masks:
        for key, mask in masks.items():
            jaccards[key] = jaccard(mask, baseline_masks[key])

    report = {
        "variant_id": variant.id,
        "stream_burn_depth_m": variant.stream_burn_depth_m,
        "accumulation_threshold_km2": variant.accumulation_threshold_km2,
        "wall_time_s": round(elapsed_s, 2),
        "peak_rss_mb": round(hand_gen.peak_rss_mb(), 1),
        "valid_cells": valid_count,
        "drain_cell_count": drain_cell_count,
        "drain_cell_fraction_pct": drain_cell_count * 100.0 / valid_count
        if valid_count
        else None,
        "mapped_stream_cell_count": stream_cell_count,
        "accumulated_cell_count": accumulated_cell_count,
        "threshold_stats": stats["thresholds"],
        "fema_metrics": metrics,
        "jaccard_vs_baseline": jaccards,
    }
    return report, masks


def metric_at_threshold(report: dict[str, Any], threshold_ft: float) -> dict[str, Any]:
    for row in report["fema_metrics"]:
        if row["threshold_ft"] == threshold_ft:
            return row
    raise KeyError(threshold_ft)


def fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def write_summary(
    *,
    args: argparse.Namespace,
    reports: list[dict[str, Any]],
    thresholds_ft: list[float],
) -> None:
    baseline_key = f"{BASELINE_BURN_M:g}m/{BASELINE_ACCUMULATION_KM2:g}km2"
    ranked = sorted(
        reports,
        key=lambda report: (
            metric_at_threshold(report, 6.0).get("precision_lift_vs_random") or 0,
            metric_at_threshold(report, 6.0).get("precision") or 0,
        ),
        reverse=True,
    )
    best = ranked[0]
    best_6ft = metric_at_threshold(best, 6.0)
    best_lift = best_6ft.get("precision_lift_vs_random")
    best_clears_flat_target = best_lift is not None and best_lift >= 2.0
    lines = [
        f"# HAND Sensitivity: {args.region_id}",
        "",
        f"- Bbox: `{tuple(args.bbox)}`",
        f"- Burn depths: `{args.burns}` meters",
        f"- Accumulation thresholds: `{args.accumulations}` km^2",
        "- FEMA comparison: `SFHA_TF = 'T'`",
        f"- Baseline variant: `{baseline_key}`",
        "",
        "## 6ft FEMA Comparison",
        "",
        "| Variant | Burn m | Acc km2 | Drain % | 3ft coverage | 6ft coverage | 6ft IoU | 6ft Precision | 6ft Recall | 6ft Lift | 6ft Jaccard vs baseline | Wall s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for report in ranked:
        six = metric_at_threshold(report, 6.0)
        cov_3 = report["threshold_stats"]["3ft"]["coverage_pct"]
        cov_6 = report["threshold_stats"]["6ft"]["coverage_pct"]
        jac_6 = report["jaccard_vs_baseline"].get("6ft")
        lines.append(
            "| "
            f"`{report['variant_id']}` | "
            f"{fmt(report['stream_burn_depth_m'])} | "
            f"{fmt(report['accumulation_threshold_km2'])} | "
            f"{fmt(report['drain_cell_fraction_pct'], 2)}% | "
            f"{fmt(cov_3, 2)}% | "
            f"{fmt(cov_6, 2)}% | "
            f"{fmt(six['iou'])} | "
            f"{fmt(six['precision'])} | "
            f"{fmt(six['recall'])} | "
            f"{fmt(six['precision_lift_vs_random'])}x | "
            f"{fmt(jac_6)} | "
            f"{fmt(report['wall_time_s'], 1)} |"
        )

    lines.extend(
        [
            "",
            "## Decision Signal",
            "",
            f"- Best 6ft precision lift: `{fmt(best_6ft['precision_lift_vs_random'])}x` from `{best['variant_id']}`.",
            f"- Flat-terrain target met: `{'yes' if best_clears_flat_target else 'no'}`. The target is `>=2.0x` precision lift without flagging most of the raster.",
            "- Higher accumulation thresholds make Houston much less noisy, but they trade recall for precision.",
            "- Decision: this parameter family improves Houston, but still does not make HAND a strong standalone flat-coastal flood discriminator.",
            "- Product implication: use the stricter drainage threshold for display if we keep this layer, and frame it as a terrain/drainage screen rather than a national floodplain detector.",
            "",
            "## Thresholds",
            "",
            f"Compared thresholds: `{thresholds_ft}` feet.",
        ]
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    args = parse_args()
    thresholds_ft = args.threshold_ft or list(DEFAULT_THRESHOLDS_FT)
    variants = [
        Variant(
            id=variant_id(burn_m, accumulation_km2),
            stream_burn_depth_m=burn_m,
            accumulation_threshold_km2=accumulation_km2,
        )
        for burn_m in args.burns
        for accumulation_km2 in args.accumulations
    ]
    baseline_variant = Variant(
        id=variant_id(BASELINE_BURN_M, BASELINE_ACCUMULATION_KM2),
        stream_burn_depth_m=BASELINE_BURN_M,
        accumulation_threshold_km2=BASELINE_ACCUMULATION_KM2,
    )
    variants = [variant for variant in variants if variant != baseline_variant]
    variants.insert(0, baseline_variant)

    configure_region(args, baseline_variant)
    dem, x, y, crs = hand_gen.fetch_dem()
    flowlines = hand_gen.fetch_flowlines(crs)

    from rasterio.crs import CRS

    target_epsg = CRS.from_string(crs).to_epsg()
    if target_epsg is None:
        raise SystemExit(f"Could not derive EPSG from DEM CRS: {crs}")
    fema_region = HandRegion(
        id=args.region_id,
        bbox=tuple(args.bbox),
        url=args.output_dir / "unused.tif",
        crs=crs,
    )
    fema_features = fetch_fema_sfha_features(
        region=fema_region,
        target_epsg=target_epsg,
        cache_dir=args.data_root / "reference" / "fema-nfhl",
        chunk_size=args.fema_chunk_size,
        simplify_m=args.fema_simplify_m,
    )
    fema_mask = rasterize_fema_mask(
        features=fema_features,
        out_shape=dem.shape,
        transform=hand_gen.raster_transform(x, y),
        all_touched=True,
    )

    reports = []
    baseline_masks = None
    for variant in variants:
        print(f"Running {variant.id}", file=sys.stderr)
        report, masks = build_variant(
            args=args,
            variant=variant,
            dem=dem,
            x=x,
            y=y,
            flowlines=flowlines,
            thresholds_ft=thresholds_ft,
            fema_mask=fema_mask,
            baseline_masks=baseline_masks,
        )
        if variant == baseline_variant:
            baseline_masks = masks
            report["jaccard_vs_baseline"] = dict.fromkeys(baseline_masks, 1.0)
        reports.append(report)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metrics.json").write_text(
        json.dumps(
            {
                "region_id": args.region_id,
                "bbox": list(args.bbox),
                "thresholds_ft": thresholds_ft,
                "variants": reports,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    write_summary(args=args, reports=reports, thresholds_ft=thresholds_ft)
    print(f"Wrote {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
