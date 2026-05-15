#!/usr/bin/env python3
"""Ingest one ORNL CFIM HUC6 archive into Floodmap's HAND COG layout."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.hand.convert_precomputed_hand import (
    build_single_region_manifest,
    convert_precomputed_hand,
    write_reports,
)

ORNL_DATASET_VERSION = "ornl-cfim-v0p21"
ORNL_SOURCE_NAME = "ORNL CFIM v0.21"
ORNL_SOURCE_URL = (
    "https://doi.ccs.ornl.gov/dataset/2461aa39-236c-5c2a-b08d-5808d926d27a"
)
ORNL_LICENSE = "Creative Commons Attribution 4.0 International (CC BY 4.0)"
ORNL_CITATION = (
    "Liu, Yan; Tarboton, David G.; Maidment, David R. Height Above Nearest "
    "Drainage (HAND) and Hydraulic Property Table for CONUS - Version 0.21 "
    "(20200601). Oak Ridge National Laboratory. DOI: 10.13139/ORNLNCCS/1630903."
)


@dataclass(frozen=True)
class OrnlHuc6Paths:
    huc: str
    archive: Path
    source_dir: Path
    source_hand: Path
    source_elevation: Path
    output_cog: Path
    temp_path: Path
    manifest_path: Path
    report_root: Path
    dataset_version: str
    region_id: str


def validate_huc(huc: str) -> str:
    normalized = huc.strip()
    if len(normalized) != 6 or not normalized.isdigit():
        raise ValueError(f"Expected a six-digit HUC6 code, got {huc!r}")
    return normalized


def default_paths(
    *,
    huc: str,
    archive: Path | None,
    data_root: Path,
    scratch_root: Path,
    report_root: Path,
) -> OrnlHuc6Paths:
    huc = validate_huc(huc)
    dataset_version = f"{ORNL_DATASET_VERSION}-{huc}"
    region_id = f"{ORNL_DATASET_VERSION}-huc6-{huc}"
    source_dir = data_root / "hand-precomputed" / "ornl-cfim-v0.21" / huc
    archive_path = archive or source_dir / f"{huc}.zip"
    return OrnlHuc6Paths(
        huc=huc,
        archive=archive_path,
        source_dir=source_dir,
        source_hand=source_dir / f"{huc}hand.tif",
        source_elevation=source_dir / f"{huc}-elevation.tif",
        output_cog=(
            data_root
            / "terrain"
            / "hand-precomputed"
            / "ornl-cfim-v0.21"
            / huc
            / f"{huc}hand-u16dm.cog.tif"
        ),
        temp_path=(
            scratch_root
            / "hand-precomputed"
            / "ornl-cfim-v0.21"
            / huc
            / f"{huc}hand-u16dm.tmp.tif"
        ),
        manifest_path=data_root / "terrain" / "manifests" / f"{dataset_version}.json",
        report_root=report_root,
        dataset_version=dataset_version,
        region_id=region_id,
    )


def zip_member_name(zip_file: zipfile.ZipFile, huc: str, filename: str) -> str:
    expected = f"{huc}/{filename}"
    names = set(zip_file.namelist())
    if expected in names:
        return expected

    suffix = f"/{filename}"
    matches = [name for name in names if name.endswith(suffix)]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ValueError(f"Multiple ZIP members match {filename!r}: {matches}")
    raise FileNotFoundError(f"ZIP archive does not contain {expected!r}")


def extract_member(
    zip_file: zipfile.ZipFile,
    *,
    member: str,
    destination: Path,
    force: bool,
) -> bool:
    if destination.exists() and not force:
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".tmp")
    with zip_file.open(member) as source, temp_path.open("wb") as target:
        while chunk := source.read(1024 * 1024):
            target.write(chunk)
    temp_path.replace(destination)
    return True


def extract_ornl_inputs(paths: OrnlHuc6Paths, *, force: bool) -> dict[str, Any]:
    if not paths.archive.exists():
        raise FileNotFoundError(paths.archive)

    with zipfile.ZipFile(paths.archive) as archive:
        hand_member = zip_member_name(archive, paths.huc, f"{paths.huc}hand.tif")
        elevation_member = zip_member_name(archive, paths.huc, f"{paths.huc}.tif")
        extracted_hand = extract_member(
            archive,
            member=hand_member,
            destination=paths.source_hand,
            force=force,
        )
        extracted_elevation = extract_member(
            archive,
            member=elevation_member,
            destination=paths.source_elevation,
            force=force,
        )

    return {
        "archive": str(paths.archive),
        "hand_member": hand_member,
        "elevation_member": elevation_member,
        "source_hand": str(paths.source_hand),
        "source_elevation": str(paths.source_elevation),
        "extracted_hand": extracted_hand,
        "extracted_elevation": extracted_elevation,
        "archive_bytes": paths.archive.stat().st_size,
        "source_hand_bytes": paths.source_hand.stat().st_size,
        "source_elevation_bytes": paths.source_elevation.stat().st_size,
    }


def source_metadata(huc: str, retrieved_at: str) -> dict[str, str]:
    return {
        "name": ORNL_SOURCE_NAME,
        "url": ORNL_SOURCE_URL,
        "license": ORNL_LICENSE,
        "citation": ORNL_CITATION,
        "retrieved_at": retrieved_at,
        "huc": huc,
    }


def ingest_ornl_huc6(
    paths: OrnlHuc6Paths,
    *,
    retrieved_at: str,
    chunk_rows: int,
    force_extract: bool,
    keep_temp: bool,
    quiet: bool,
    extract_only: bool,
) -> dict[str, Any]:
    extraction = extract_ornl_inputs(paths, force=force_extract)
    serialized_paths = {key: str(value) for key, value in paths.__dict__.items()}
    if extract_only:
        return {"paths": serialized_paths, "extraction": extraction}

    metrics = convert_precomputed_hand(
        source_raster=str(paths.source_hand),
        output_cog=paths.output_cog,
        temp_path=paths.temp_path,
        chunk_rows=chunk_rows,
        quiet=quiet,
    )
    source_profile = metrics["source_profile"]
    manifest = build_single_region_manifest(
        dataset_version=paths.dataset_version,
        region_id=paths.region_id,
        output_cog=paths.output_cog,
        crs=source_profile["crs"],
        bounds=tuple(source_profile["bounds"]),
        source_metadata=source_metadata(paths.huc, retrieved_at),
    )
    write_reports(
        metrics=metrics,
        manifest=manifest,
        manifest_path=paths.manifest_path,
        report_root=paths.report_root,
        region_id=paths.region_id,
        source_name=ORNL_SOURCE_NAME,
        huc=paths.huc,
    )
    if not keep_temp:
        paths.temp_path.unlink(missing_ok=True)

    return {
        "paths": serialized_paths,
        "extraction": extraction,
        "metrics": metrics,
        "manifest": manifest,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--huc", required=True, help="Six-digit HUC6 code.")
    parser.add_argument("--zip-path", type=Path, help="ORNL HUC6 ZIP path.")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("/mnt/storage/floodmap/data"),
        help="Floodmap data root for source rasters, COGs, and manifests.",
    )
    parser.add_argument(
        "--scratch-root",
        type=Path,
        default=Path("/mnt/storage/floodmap/scratch"),
        help="Floodmap scratch root for temporary conversion files.",
    )
    parser.add_argument(
        "--report-root",
        type=Path,
        default=Path("docs/qa/hand-precomputed"),
        help="Report root inside the repo checkout.",
    )
    parser.add_argument(
        "--retrieved-at",
        default=date.today().isoformat(),
        help="Dataset retrieval date to record in the manifest.",
    )
    parser.add_argument("--chunk-rows", type=int, default=512)
    parser.add_argument("--force-extract", action="store_true")
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Extract HAND/elevation rasters but do not convert to COG.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = default_paths(
        huc=args.huc,
        archive=args.zip_path,
        data_root=args.data_root,
        scratch_root=args.scratch_root,
        report_root=args.report_root,
    )
    result = ingest_ornl_huc6(
        paths,
        retrieved_at=args.retrieved_at,
        chunk_rows=args.chunk_rows,
        force_extract=args.force_extract,
        keep_temp=args.keep_temp,
        quiet=args.quiet,
        extract_only=args.extract_only,
    )
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
