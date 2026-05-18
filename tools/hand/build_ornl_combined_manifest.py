#!/usr/bin/env python3
"""Build a multi-HUC ORNL CFIM terrain manifest from per-HUC manifests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ORNL_DATASET_PREFIX = "ornl-cfim-v0p21"


def validate_huc(huc: str) -> str:
    normalized = huc.strip()
    if len(normalized) != 6 or not normalized.isdigit():
        raise ValueError(f"Expected a six-digit HUC6 code, got {huc!r}")
    return normalized


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def region_from_huc_manifest(manifest: dict[str, Any], huc: str) -> dict[str, Any]:
    hand_layer = manifest.get("layers", {}).get("hand")
    if not hand_layer:
        raise ValueError(f"{huc}: manifest has no hand layer")
    regions = hand_layer.get("regions") or []
    if len(regions) != 1:
        raise ValueError(f"{huc}: expected exactly one hand region, got {len(regions)}")
    return dict(regions[0])


def elevation_region_from_hand_region(
    region: dict[str, Any], huc: str, data_root: Path
) -> dict[str, Any]:
    elevation_region = dict(region)
    elevation_region["id"] = f"ornl-cfim-v0p21-huc6-{huc}-elevation"
    elevation_region["url"] = str(
        data_root
        / "hand-precomputed"
        / "ornl-cfim-v0.21"
        / huc
        / f"{huc}-elevation.tif"
    )
    return elevation_region


def build_combined_manifest(
    *,
    hucs: list[str],
    manifest_root: Path,
    dataset_version: str,
    elevation_data_root: Path | None = None,
) -> dict[str, Any]:
    regions = []
    elevation_regions = []
    source_items = []
    for raw_huc in hucs:
        huc = validate_huc(raw_huc)
        source_manifest = load_manifest(
            manifest_root / f"{ORNL_DATASET_PREFIX}-{huc}.json"
        )
        region = region_from_huc_manifest(source_manifest, huc)
        regions.append(region)
        if elevation_data_root is not None:
            elevation_regions.append(
                elevation_region_from_hand_region(region, huc, elevation_data_root)
            )
        source = source_manifest.get("source")
        if source:
            source_items.append(source)

    layers: dict[str, Any] = {
        "hand": {
            "encoding": "uint16-decimeters",
            "nodata": 65535,
            "regions": regions,
        }
    }
    if elevation_regions:
        layers["elevation"] = {
            "encoding": "elevation-meter-range",
            "nodata": 65535,
            "regions": elevation_regions,
        }

    return {
        "schema_version": 1,
        "dataset_version": dataset_version,
        "layers": layers,
        "source": {
            "name": "ORNL CFIM v0.21",
            "components": source_items,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--huc",
        action="append",
        required=True,
        help="HUC6 code to include. Repeat in desired priority order.",
    )
    parser.add_argument(
        "--manifest-root",
        type=Path,
        default=Path("/mnt/storage/floodmap/data/terrain/manifests"),
        help="Directory containing per-HUC ORNL manifests.",
    )
    parser.add_argument(
        "--dataset-version",
        required=True,
        help="Dataset version for the combined manifest.",
    )
    parser.add_argument(
        "--elevation-data-root",
        type=Path,
        default=None,
        help="Optional Floodmap data root. When set, add ORNL elevation rasters as an elevation layer.",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_combined_manifest(
        hucs=args.huc,
        manifest_root=args.manifest_root,
        dataset_version=args.dataset_version,
        elevation_data_root=args.elevation_data_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
