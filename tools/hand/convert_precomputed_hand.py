#!/usr/bin/env python3
"""Convert precomputed float HAND rasters to Floodmap uint16-decimeter COGs."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.shutil import copy as rio_copy
from rasterio.windows import Window

U16_NODATA = 65535


def encode_hand_window(
    values: np.ndarray,
    *,
    source_nodata: float | int | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Encode HAND meters as uint16 decimeters.

    The app's terrain-v2 path expects uint16 decimeters with 65535 as nodata.
    Valid source values are finite, non-negative meters. Values above 6553.4m
    are clipped to the largest valid uint16 code.
    """

    values = np.asarray(values, dtype=np.float32)
    valid = np.isfinite(values) & (values >= 0.0)
    if source_nodata is not None and np.isfinite(source_nodata):
        valid &= values != source_nodata

    encoded = np.full(values.shape, U16_NODATA, dtype=np.uint16)
    if np.any(valid):
        scaled = np.rint(values[valid] * 10.0)
        scaled = np.clip(scaled, 0, U16_NODATA - 1)
        encoded[valid] = scaled.astype(np.uint16)
    return encoded, valid


def update_histogram(histogram: np.ndarray, encoded: np.ndarray) -> int:
    valid = encoded != U16_NODATA
    valid_count = int(np.count_nonzero(valid))
    if valid_count:
        histogram += np.bincount(
            encoded[valid].astype(np.int64),
            minlength=histogram.size,
        )
    return valid_count


def percentile_from_histogram(histogram: np.ndarray, percentile: float) -> float | None:
    total = int(histogram.sum())
    if total == 0:
        return None

    rank = int(np.ceil((percentile / 100.0) * total)) - 1
    rank = max(0, min(rank, total - 1))
    cumulative = np.cumsum(histogram)
    encoded_value = int(np.searchsorted(cumulative, rank + 1, side="left"))
    return round(encoded_value / 10.0, 3)


def summarize_histogram(histogram: np.ndarray, total_cells: int) -> dict[str, Any]:
    valid_cells = int(histogram.sum())
    nodata_cells = int(total_cells - valid_cells)

    metrics: dict[str, Any] = {
        "total_cells": int(total_cells),
        "valid_cells": valid_cells,
        "nodata_cells": nodata_cells,
        "valid_fraction": valid_cells / total_cells if total_cells else 0.0,
        "nodata_fraction": nodata_cells / total_cells if total_cells else 0.0,
        "hand_m": {
            "min": None,
            "p50": percentile_from_histogram(histogram, 50),
            "p95": percentile_from_histogram(histogram, 95),
            "p99": percentile_from_histogram(histogram, 99),
            "max": None,
        },
        "cells_below_threshold_ft": {},
    }

    if valid_cells:
        valid_indices = np.flatnonzero(histogram)
        metrics["hand_m"]["min"] = round(float(valid_indices[0]) / 10.0, 3)
        metrics["hand_m"]["max"] = round(float(valid_indices[-1]) / 10.0, 3)

    for threshold_ft in (1, 3, 6, 10, 20, 30):
        threshold_dm = int(round(threshold_ft * 0.3048 * 10.0))
        count = int(histogram[: threshold_dm + 1].sum())
        metrics["cells_below_threshold_ft"][str(threshold_ft)] = {
            "cells": count,
            "fraction_of_valid": count / valid_cells if valid_cells else 0.0,
        }

    return metrics


def build_single_region_manifest(
    *,
    dataset_version: str,
    region_id: str,
    output_cog: Path,
    crs: str,
    bounds: tuple[float, float, float, float],
    source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "dataset_version": dataset_version,
        "layers": {
            "hand": {
                "encoding": "uint16-decimeters",
                "nodata": U16_NODATA,
                "regions": [
                    {
                        "id": region_id,
                        "bbox": list(bounds),
                        "crs": crs,
                        "url": str(output_cog),
                    }
                ],
            }
        },
    }
    if source_metadata:
        manifest["source"] = source_metadata
    return manifest


def convert_precomputed_hand(
    *,
    source_raster: str,
    output_cog: Path,
    temp_path: Path,
    chunk_rows: int = 512,
    quiet: bool = False,
) -> dict[str, Any]:
    start = time.monotonic()
    output_cog.parent.mkdir(parents=True, exist_ok=True)
    temp_path.parent.mkdir(parents=True, exist_ok=True)

    histogram = np.zeros(U16_NODATA, dtype=np.int64)

    with rasterio.open(source_raster) as src:
        source_profile = {
            "driver": src.driver,
            "width": src.width,
            "height": src.height,
            "count": src.count,
            "dtype": src.dtypes[0],
            "crs": str(src.crs),
            "bounds": [
                src.bounds.left,
                src.bounds.bottom,
                src.bounds.right,
                src.bounds.top,
            ],
            "nodata": src.nodata,
            "block_shapes": [list(shape) for shape in src.block_shapes],
            "overviews": src.overviews(1),
            "compression": str(src.compression) if src.compression else None,
            "is_tiled": src.is_tiled,
        }

        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            dtype="uint16",
            count=1,
            nodata=U16_NODATA,
            tiled=True,
            blockxsize=512,
            blockysize=512,
            compress="DEFLATE",
            predictor=2,
            BIGTIFF="IF_SAFER",
        )

        total_cells = src.width * src.height
        with rasterio.open(temp_path, "w", **profile) as dst:
            for row_start in range(0, src.height, chunk_rows):
                row_count = min(chunk_rows, src.height - row_start)
                window = Window(0, row_start, src.width, row_count)
                source_values = src.read(1, window=window, masked=False)
                encoded, _valid = encode_hand_window(
                    source_values,
                    source_nodata=src.nodata,
                )
                dst.write(encoded, 1, window=window)
                update_histogram(histogram, encoded)

                if not quiet and (
                    row_start == 0
                    or row_start + row_count == src.height
                    or (row_start // chunk_rows) % 10 == 0
                ):
                    elapsed = time.monotonic() - start
                    print(
                        f"encoded rows {row_start + row_count}/{src.height} "
                        f"({elapsed:.1f}s)",
                        flush=True,
                    )

        rio_copy(
            temp_path,
            output_cog,
            driver="COG",
            compress="DEFLATE",
            predictor=2,
            overview_resampling="nearest",
            BIGTIFF="IF_SAFER",
        )

    with rasterio.open(output_cog) as out:
        output_profile = {
            "driver": out.driver,
            "width": out.width,
            "height": out.height,
            "dtype": out.dtypes[0],
            "crs": str(out.crs),
            "bounds": [
                out.bounds.left,
                out.bounds.bottom,
                out.bounds.right,
                out.bounds.top,
            ],
            "nodata": out.nodata,
            "block_shapes": [list(shape) for shape in out.block_shapes],
            "overviews": out.overviews(1),
            "compression": str(out.compression) if out.compression else None,
            "is_tiled": out.is_tiled,
        }

    return {
        "source_raster": source_raster,
        "output_cog": str(output_cog),
        "temp_path": str(temp_path),
        "output_bytes": output_cog.stat().st_size,
        "elapsed_seconds": round(time.monotonic() - start, 3),
        "source_profile": source_profile,
        "output_profile": output_profile,
        "encoding": {
            "name": "uint16-decimeters",
            "nodata": U16_NODATA,
            "meters_per_unit": 0.1,
        },
        "summary": summarize_histogram(histogram, total_cells),
    }


def write_reports(
    *,
    metrics: dict[str, Any],
    manifest: dict[str, Any] | None,
    manifest_path: Path | None,
    report_root: Path,
    region_id: str,
    source_name: str,
    huc: str | None,
) -> None:
    report_dir = report_root / region_id
    report_dir.mkdir(parents=True, exist_ok=True)

    metrics_path = report_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")

    if manifest is not None:
        manifest_json = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        (report_dir / "manifest.json").write_text(manifest_json)
        if manifest_path is not None:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(manifest_json)

    summary = metrics["summary"]
    source = metrics["source_profile"]
    output = metrics["output_profile"]
    lines = [
        f"# {source_name} Precomputed HAND Ingest",
        "",
        f"- Region: `{region_id}`",
        f"- HUC: `{huc or 'n/a'}`",
        f"- Source raster: `{metrics['source_raster']}`",
        f"- Output COG: `{metrics['output_cog']}`",
        f"- Output size: {metrics['output_bytes']:,} bytes",
        f"- Manifest: `{manifest_path}`"
        if manifest_path
        else "- Manifest: not written",
        f"- Report manifest copy: `{report_dir / 'manifest.json'}`",
        f"- Elapsed: {metrics['elapsed_seconds']} seconds",
        "",
        "## Source",
        "",
        f"- Size: {source['width']:,} x {source['height']:,}",
        f"- CRS: `{source['crs']}`",
        f"- Bounds: `{source['bounds']}`",
        f"- Dtype/nodata: `{source['dtype']}` / `{source['nodata']}`",
        f"- Tiled/blocks: `{source['is_tiled']}` / `{source['block_shapes']}`",
        f"- Overviews: `{source['overviews']}`",
        "",
        "## Output",
        "",
        f"- Size: {output['width']:,} x {output['height']:,}",
        f"- CRS: `{output['crs']}`",
        f"- Dtype/nodata: `{output['dtype']}` / `{output['nodata']}`",
        f"- Tiled/blocks: `{output['is_tiled']}` / `{output['block_shapes']}`",
        f"- Overviews: `{output['overviews']}`",
        "",
        "## Encoded HAND Distribution",
        "",
        f"- Total cells: {summary['total_cells']:,}",
        f"- Valid cells: {summary['valid_cells']:,} ({summary['valid_fraction']:.3%})",
        f"- Nodata cells: {summary['nodata_cells']:,} "
        f"({summary['nodata_fraction']:.3%})",
        f"- HAND min/p50/p95/p99/max meters: "
        f"{summary['hand_m']['min']} / {summary['hand_m']['p50']} / "
        f"{summary['hand_m']['p95']} / {summary['hand_m']['p99']} / "
        f"{summary['hand_m']['max']}",
        "",
        "## Low-HAND Coverage",
        "",
    ]

    for threshold_ft, item in sorted(
        summary["cells_below_threshold_ft"].items(), key=lambda value: float(value[0])
    ):
        lines.append(
            f"- <= {threshold_ft} ft: {item['cells']:,} cells "
            f"({item['fraction_of_valid']:.3%} of valid)"
        )

    (report_dir / "summary.md").write_text("\n".join(lines) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-raster", required=True)
    parser.add_argument("--output-cog", type=Path, required=True)
    parser.add_argument("--temp-path", type=Path, required=True)
    parser.add_argument("--manifest-path", type=Path)
    parser.add_argument(
        "--report-root", type=Path, default=Path("docs/qa/hand-precomputed")
    )
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--region-id", required=True)
    parser.add_argument("--source-name", default="Precomputed HAND")
    parser.add_argument("--source-url")
    parser.add_argument("--license")
    parser.add_argument("--citation")
    parser.add_argument("--retrieved-at")
    parser.add_argument("--huc")
    parser.add_argument("--chunk-rows", type=int, default=512)
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metrics = convert_precomputed_hand(
        source_raster=args.source_raster,
        output_cog=args.output_cog,
        temp_path=args.temp_path,
        chunk_rows=args.chunk_rows,
        quiet=args.quiet,
    )

    source_profile = metrics["source_profile"]
    source_metadata = {
        key: value
        for key, value in {
            "name": args.source_name,
            "url": args.source_url,
            "license": args.license,
            "citation": args.citation,
            "retrieved_at": args.retrieved_at,
            "huc": args.huc,
        }.items()
        if value
    }
    manifest = build_single_region_manifest(
        dataset_version=args.dataset_version,
        region_id=args.region_id,
        output_cog=args.output_cog,
        crs=source_profile["crs"],
        bounds=tuple(source_profile["bounds"]),
        source_metadata=source_metadata,
    )

    write_reports(
        metrics=metrics,
        manifest=manifest if args.manifest_path else None,
        manifest_path=args.manifest_path,
        report_root=args.report_root,
        region_id=args.region_id,
        source_name=args.source_name,
        huc=args.huc,
    )

    if not args.keep_temp:
        args.temp_path.unlink(missing_ok=True)

    print(json.dumps(metrics, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
