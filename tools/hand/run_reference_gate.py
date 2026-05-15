#!/usr/bin/env python3
"""Run the HAND-vs-NFHL reference gate with rasterization sensitivity."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def metrics_path(output_dir: Path, region: str) -> Path:
    return output_dir / region / "metrics.json"


def load_metrics(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def threshold_rows(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(metrics["thresholds"], key=lambda item: float(item["threshold_ft"]))


def format_pct(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.2f}%"


def format_float(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.3f}"


def write_sensitivity_report(
    *,
    all_touched_metrics: dict[str, Any],
    strict_metrics: dict[str, Any],
    output_path: Path,
) -> None:
    all_rows = {
        float(row["threshold_ft"]): row for row in threshold_rows(all_touched_metrics)
    }
    strict_rows = {
        float(row["threshold_ft"]): row for row in threshold_rows(strict_metrics)
    }
    thresholds = sorted(set(all_rows) & set(strict_rows))

    lines = [
        "# Rasterization Sensitivity",
        "",
        "This compares FEMA NFHL rasterization with `all_touched=true` against",
        "strict center-point rasterization on the same HAND grid.",
        "",
        "## Coverage",
        "",
        f"- All touched: FEMA cells {all_touched_metrics['fema_total_cells']:,}; "
        f"FEMA in HAND nodata {all_touched_metrics['fema_in_hand_nodata_cells']:,} "
        f"({format_pct(all_touched_metrics['fema_in_hand_nodata_pct'])})",
        f"- Strict: FEMA cells {strict_metrics['fema_total_cells']:,}; "
        f"FEMA in HAND nodata {strict_metrics['fema_in_hand_nodata_cells']:,} "
        f"({format_pct(strict_metrics['fema_in_hand_nodata_pct'])})",
        "",
        "## Thresholds",
        "",
        "| Threshold | All touched precision | Strict precision | All touched recall | Strict recall | All touched low-elev lift | Strict low-elev lift |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for threshold in thresholds:
        touched = all_rows[threshold]
        strict = strict_rows[threshold]
        lines.append(
            f"| {threshold:g} ft | "
            f"{format_float(touched['precision'])} | "
            f"{format_float(strict['precision'])} | "
            f"{format_float(touched['recall'])} | "
            f"{format_float(strict['recall'])} | "
            f"{format_float(touched.get('precision_lift_vs_low_elevation'))} | "
            f"{format_float(strict.get('precision_lift_vs_low_elevation'))} |"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compare_command(
    *,
    script: Path,
    manifest: Path,
    region: str,
    output_dir: Path,
    cache_dir: Path | None,
    baseline_raster: Path | None,
    chunk_size: int,
    simplify_m: float,
    max_image_dim: int,
    all_touched: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(script),
        "--manifest",
        str(manifest),
        "--region",
        region,
        "--output-dir",
        str(output_dir),
        "--chunk-size",
        str(chunk_size),
        "--simplify-m",
        str(simplify_m),
        "--max-image-dim",
        str(max_image_dim),
    ]
    if cache_dir is not None:
        command.extend(["--cache-dir", str(cache_dir)])
    if baseline_raster is not None:
        command.extend(["--baseline-raster", str(baseline_raster)])
    if not all_touched:
        command.append("--no-all-touched")
    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--baseline-raster", type=Path)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("docs/qa/hand-reference"),
        help="Root directory for reference validation outputs.",
    )
    parser.add_argument(
        "--compare-script",
        type=Path,
        default=Path(__file__).with_name("compare_to_reference.py"),
    )
    parser.add_argument("--chunk-size", type=int, default=100)
    parser.add_argument("--simplify-m", type=float, default=5.0)
    parser.add_argument("--max-image-dim", type=int, default=1800)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    all_touched_dir = args.output_root / args.region
    strict_dir = args.output_root / f"{args.region}-no-all-touched"

    for output_dir, all_touched in (
        (all_touched_dir, True),
        (strict_dir, False),
    ):
        command = compare_command(
            script=args.compare_script,
            manifest=args.manifest,
            region=args.region,
            output_dir=output_dir,
            cache_dir=args.cache_dir,
            baseline_raster=args.baseline_raster,
            chunk_size=args.chunk_size,
            simplify_m=args.simplify_m,
            max_image_dim=args.max_image_dim,
            all_touched=all_touched,
        )
        subprocess.run(command, check=True)

    write_sensitivity_report(
        all_touched_metrics=load_metrics(metrics_path(all_touched_dir, args.region)),
        strict_metrics=load_metrics(metrics_path(strict_dir, args.region)),
        output_path=all_touched_dir / "sensitivity.md",
    )


if __name__ == "__main__":
    main()
