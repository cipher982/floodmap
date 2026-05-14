#!/usr/bin/env python3
"""Emit dry-run CONUS HAND manifests and region job plans."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class RepresentativeRegion:
    id: str
    bbox: tuple[float, float, float, float]
    crs: str
    source_url: str
    vpu_or_hu4: str
    notes: str


REPRESENTATIVE_REGIONS: dict[str, RepresentativeRegion] = {
    "birmingham-prototype": RepresentativeRegion(
        id="birmingham-prototype",
        bbox=(-87.02, 33.30, -86.52, 33.75),
        crs="EPSG:5070",
        source_url="file://data/terrain/hand/birmingham-drainage.tif",
        vpu_or_hu4="0315/0316 smoke region",
        notes="Existing validated inland creek-corridor prototype.",
    ),
    "houston-bayou-pilot": RepresentativeRegion(
        id="houston-bayou-pilot",
        bbox=(-95.82, 29.45, -94.95, 30.15),
        crs="EPSG:5070",
        source_url="file://data/terrain/hand/houston-bayou.cog.tif",
        vpu_or_hu4="1204 pilot",
        notes="Flat Gulf Coast bayou metro; useful contrast against Birmingham relief.",
    ),
    "denver-front-range-pilot": RepresentativeRegion(
        id="denver-front-range-pilot",
        bbox=(-105.35, 39.45, -104.55, 40.10),
        crs="EPSG:5070",
        source_url="file://data/terrain/hand/denver-front-range.cog.tif",
        vpu_or_hu4="1019 pilot",
        notes="Semi-arid steep-gradient urban corridor; catches slope/stream-order artifacts.",
    ),
}

QA_METRICS = [
    "source_dem_cells",
    "valid_hand_cells",
    "nodata_cells",
    "mapped_flowline_count",
    "burned_or_enforced_drainage_count",
    "hand_p05_m",
    "hand_p50_m",
    "hand_p95_m",
    "hand_p99_m",
    "source_cog_bytes",
    "z12_tile_p95_ms",
    "z14_tile_p95_ms",
    "sample_png_paths",
]


def select_regions(region_ids: list[str]) -> list[RepresentativeRegion]:
    selected = []
    for region_id in region_ids:
        try:
            selected.append(REPRESENTATIVE_REGIONS[region_id])
        except KeyError as exc:
            known = ", ".join(sorted(REPRESENTATIVE_REGIONS))
            raise SystemExit(f"Unknown region {region_id!r}. Known: {known}") from exc
    return selected


def build_terrain_manifest(
    dataset_version: str, regions: list[RepresentativeRegion]
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "dataset_version": dataset_version,
        "layers": {
            "hand": {
                "encoding": "uint16-decimeters",
                "nodata": 65535,
                "regions": [
                    {
                        "id": region.id,
                        "bbox": list(region.bbox),
                        "crs": region.crs,
                        "url": region.source_url,
                    }
                    for region in regions
                ],
            }
        },
    }


def build_region_job(
    region: RepresentativeRegion,
    *,
    dataset_version: str,
    min_precompute_zoom: int,
    max_precompute_zoom: int,
    max_dynamic_zoom: int,
) -> dict[str, object]:
    return {
        "id": region.id,
        "dataset_version": dataset_version,
        "bbox": list(region.bbox),
        "crs": region.crs,
        "vpu_or_hu4": region.vpu_or_hu4,
        "source_url": region.source_url,
        "notes": region.notes,
        "inputs": {
            "hydrography": {
                "family": "NHDPlus HR or 3DHP",
                "required_assets": [
                    "flowlines",
                    "catchments",
                    "flow direction",
                    "flow accumulation",
                    "hydro-enforced elevation if available",
                ],
            },
            "terrain": {
                "family": "3DEP 10m DEM",
                "required_assets": ["source DEM", "metadata", "checksums"],
            },
        },
        "stages": [
            {
                "name": "download_verify_inputs",
                "done": [
                    "all referenced input files exist",
                    "checksums or byte sizes are recorded",
                    "input CRS/resolution/nodata are recorded",
                ],
            },
            {
                "name": "compute_hand",
                "done": [
                    "drainage network selected",
                    "flow paths resolved",
                    "height above downstream drainage encoded as uint16 decimeters",
                ],
            },
            {
                "name": "write_source_cog",
                "done": [
                    "COG has internal tiling",
                    "COG has overviews for low zoom reads",
                    "manifest region URL points at immutable COG path",
                ],
            },
            {
                "name": "precompute_cache",
                "min_zoom": min_precompute_zoom,
                "max_zoom": max_precompute_zoom,
                "done": ["z9-z12 cache tiles are written or skipped as source-nodata"],
            },
            {
                "name": "qa_metrics",
                "metrics": QA_METRICS,
                "done": ["metrics JSON and sample images exist for review"],
            },
        ],
        "serving": {
            "dynamic_max_zoom": max_dynamic_zoom,
            "sample_cache_zoom": 12,
            "sample_note": "Cache-backed samples are approximate at TERRAIN_SAMPLE_CACHE_ZOOM.",
        },
    }


def build_job_manifest(
    dataset_version: str,
    regions: list[RepresentativeRegion],
    *,
    min_precompute_zoom: int,
    max_precompute_zoom: int,
    max_dynamic_zoom: int,
    cache_budget_gb: int,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "dataset_version": dataset_version,
        "cache_budget_bytes": cache_budget_gb * 1024**3,
        "precompute": {
            "min_zoom": min_precompute_zoom,
            "max_zoom": max_precompute_zoom,
            "parallelism": {
                "strategy": "tile-column sharding plus --workers per region",
                "example": "--shard-count 8 --shard-index 0 --workers 4",
            },
        },
        "mosaic_rule": {
            "tile_selection": "choose intersecting source regions by manifest order",
            "overlap_policy": "prefer first region until measured overlap QA requires a priority field",
            "cache_key": "{layer}/{dataset_version}/{z}/{x}/{y}.u16.br",
        },
        "regions": [
            build_region_job(
                region,
                dataset_version=dataset_version,
                min_precompute_zoom=min_precompute_zoom,
                max_precompute_zoom=max_precompute_zoom,
                max_dynamic_zoom=max_dynamic_zoom,
            )
            for region in regions
        ],
    }


def build_plan(args: argparse.Namespace) -> dict[str, object]:
    regions = select_regions(args.regions)
    return {
        "terrain_manifest": build_terrain_manifest(args.dataset_version, regions),
        "job_manifest": build_job_manifest(
            args.dataset_version,
            regions,
            min_precompute_zoom=args.min_precompute_zoom,
            max_precompute_zoom=args.max_precompute_zoom,
            max_dynamic_zoom=args.max_dynamic_zoom,
            cache_budget_gb=args.cache_budget_gb,
        ),
        "representative_regions": [asdict(region) for region in regions],
    }


def write_plan(output_dir: Path, plan: dict[str, object]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    terrain_path = output_dir / "terrain-manifest.json"
    jobs_path = output_dir / "build-jobs.json"
    terrain_path.write_text(
        json.dumps(plan["terrain_manifest"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    jobs_path.write_text(
        json.dumps(plan["job_manifest"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "terrain_manifest": str(terrain_path),
        "job_manifest": str(jobs_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Emit a dry-run CONUS HAND terrain manifest and build job manifest."
    )
    parser.add_argument("--dataset-version", default="hand-conus-dryrun")
    parser.add_argument(
        "--region",
        dest="regions",
        action="append",
        choices=sorted(REPRESENTATIVE_REGIONS),
        help="Representative region id. Repeat to include multiple regions.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/terrain/dry-run"))
    parser.add_argument("--min-precompute-zoom", type=int, default=9)
    parser.add_argument("--max-precompute-zoom", type=int, default=12)
    parser.add_argument("--max-dynamic-zoom", type=int, default=14)
    parser.add_argument("--cache-budget-gb", type=int, default=100)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.regions is None:
        args.regions = ["birmingham-prototype", "houston-bayou-pilot"]
    return args


def main() -> None:
    args = parse_args()
    plan = build_plan(args)
    if not args.no_write:
        plan["written"] = write_plan(args.output_dir, plan)
    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return

    region_ids = ", ".join(
        region["id"]
        for region in plan["representative_regions"]  # type: ignore[index]
    )
    print("CONUS HAND dry-run plan")
    print(f"  dataset_version: {args.dataset_version}")
    print(f"  regions: {region_ids}")
    if not args.no_write:
        written = plan["written"]  # type: ignore[index]
        print(f"  terrain manifest: {written['terrain_manifest']}")
        print(f"  job manifest: {written['job_manifest']}")


if __name__ == "__main__":
    main()
