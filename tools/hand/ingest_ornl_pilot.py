#!/usr/bin/env python3
"""Ingest a small ORNL CFIM HUC set and rebuild a combined manifest."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.hand.build_ornl_combined_manifest import (
    build_combined_manifest,
    validate_huc,
)

DEFAULT_DATA_ROOT = Path("/mnt/storage/floodmap/data")
DEFAULT_SCRATCH_ROOT = Path("/mnt/storage/floodmap/scratch")
DEFAULT_SOURCE_ROOTS = [
    DEFAULT_DATA_ROOT / "hand-precomputed" / "ornl-cfim-v0.21" / "source-zips",
    Path("/home/drose/floodmap-data/hand-precomputed/ornl-cfim-v0.21/source-zips"),
]
DEFAULT_SOUTHEAST_HUCS = ["031601", "031502", "031501", "031300", "030701", "030501"]
DEFAULT_DATASET_VERSION = "ornl-cfim-v0p21-southeast-pilot"


@dataclass(frozen=True)
class HucState:
    huc: str
    archive: str | None
    manifest: str | None
    status: str


def normalize_hucs(hucs: list[str]) -> list[str]:
    normalized: list[str] = []
    seen = set()
    for huc in hucs:
        validated = validate_huc(huc)
        if validated not in seen:
            normalized.append(validated)
            seen.add(validated)
    return normalized


def find_huc_archive(huc: str, source_roots: list[Path]) -> Path | None:
    filename = f"{validate_huc(huc)}.zip"
    for root in source_roots:
        candidate = root / filename
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


def huc_manifest_path(manifest_root: Path, huc: str) -> Path:
    return manifest_root / f"ornl-cfim-v0p21-{validate_huc(huc)}.json"


def ensure_huc_ingested(
    *,
    huc: str,
    archive: Path,
    data_root: Path,
    scratch_root: Path,
    report_root: Path,
    retrieved_at: str,
    chunk_rows: int,
    force: bool,
    skip_archive_hash: bool,
    quiet: bool,
    dry_run: bool,
) -> dict[str, Any] | None:
    manifest_path = huc_manifest_path(data_root / "terrain" / "manifests", huc)
    if manifest_path.exists() and not force:
        return None
    if dry_run:
        return {"dry_run": True, "huc": huc, "archive": str(archive)}

    from tools.hand.ingest_ornl_huc6 import default_paths, ingest_ornl_huc6

    paths = default_paths(
        huc=huc,
        archive=archive,
        data_root=data_root,
        scratch_root=scratch_root,
        report_root=report_root,
    )
    return ingest_ornl_huc6(
        paths,
        retrieved_at=retrieved_at,
        chunk_rows=chunk_rows,
        force_extract=force,
        hash_archive=not skip_archive_hash,
        keep_temp=False,
        quiet=quiet,
        extract_only=False,
        dry_run=False,
    )


def build_pilot_manifest(
    *,
    hucs: list[str],
    source_roots: list[Path],
    data_root: Path,
    scratch_root: Path,
    report_root: Path,
    manifest_root: Path,
    output: Path,
    dataset_version: str,
    retrieved_at: str,
    chunk_rows: int,
    force: bool,
    allow_missing: bool,
    skip_archive_hash: bool,
    quiet: bool,
    dry_run: bool,
) -> dict[str, Any]:
    states: list[HucState] = []
    included_hucs: list[str] = []
    ingested_hucs: list[str] = []
    missing_hucs: list[str] = []

    for huc in normalize_hucs(hucs):
        archive = find_huc_archive(huc, source_roots)
        manifest_path = huc_manifest_path(manifest_root, huc)
        if archive is None and not manifest_path.exists():
            missing_hucs.append(huc)
            states.append(
                HucState(huc=huc, archive=None, manifest=None, status="missing")
            )
            continue

        if archive is not None:
            result = ensure_huc_ingested(
                huc=huc,
                archive=archive,
                data_root=data_root,
                scratch_root=scratch_root,
                report_root=report_root,
                retrieved_at=retrieved_at,
                chunk_rows=chunk_rows,
                force=force,
                skip_archive_hash=skip_archive_hash,
                quiet=quiet,
                dry_run=dry_run,
            )
            if result is not None:
                ingested_hucs.append(huc)

        if manifest_path.exists() or dry_run:
            included_hucs.append(huc)
            states.append(
                HucState(
                    huc=huc,
                    archive=str(archive) if archive else None,
                    manifest=str(manifest_path),
                    status="ready",
                )
            )
        else:
            missing_hucs.append(huc)
            states.append(
                HucState(
                    huc=huc,
                    archive=str(archive) if archive else None,
                    manifest=None,
                    status="missing_manifest",
                )
            )

    if missing_hucs and not allow_missing:
        raise SystemExit(
            "Missing required HUC ZIPs/manifests: "
            + ", ".join(sorted(set(missing_hucs)))
        )
    if not included_hucs:
        raise SystemExit("No HUC manifests are available to combine.")

    manifest: dict[str, Any] | None = None
    if not dry_run:
        manifest = build_combined_manifest(
            hucs=included_hucs,
            manifest_root=manifest_root,
            dataset_version=dataset_version,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    return {
        "dataset_version": dataset_version,
        "output": str(output),
        "included_hucs": included_hucs,
        "ingested_hucs": ingested_hucs,
        "missing_hucs": sorted(set(missing_hucs)),
        "states": [state.__dict__ for state in states],
        "dry_run": dry_run,
        "manifest_region_count": (
            len(manifest["layers"]["hand"]["regions"]) if manifest is not None else None
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--huc",
        action="append",
        help=(
            "HUC6 to include, repeatable. Defaults to the Southeast pilot order: "
            + ", ".join(DEFAULT_SOUTHEAST_HUCS)
        ),
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        action="append",
        help="Directory containing ORNL HUC6 ZIPs. Repeatable.",
    )
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--scratch-root", type=Path, default=DEFAULT_SCRATCH_ROOT)
    parser.add_argument(
        "--report-root", type=Path, default=Path("docs/qa/hand-precomputed")
    )
    parser.add_argument(
        "--manifest-root",
        type=Path,
        help="Per-HUC manifest directory. Defaults to DATA_ROOT/terrain/manifests.",
    )
    parser.add_argument("--dataset-version", default=DEFAULT_DATASET_VERSION)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--retrieved-at", default=date.today().isoformat())
    parser.add_argument("--chunk-rows", type=int, default=512)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--allow-missing", action="store_true")
    parser.add_argument("--skip-archive-hash", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest_root = args.manifest_root or args.data_root / "terrain" / "manifests"
    output = args.output or manifest_root / f"{args.dataset_version}.json"
    result = build_pilot_manifest(
        hucs=args.huc or DEFAULT_SOUTHEAST_HUCS,
        source_roots=args.source_root or DEFAULT_SOURCE_ROOTS,
        data_root=args.data_root,
        scratch_root=args.scratch_root,
        report_root=args.report_root,
        manifest_root=manifest_root,
        output=output,
        dataset_version=args.dataset_version,
        retrieved_at=args.retrieved_at,
        chunk_rows=args.chunk_rows,
        force=args.force,
        allow_missing=args.allow_missing,
        skip_archive_hash=args.skip_archive_hash,
        quiet=args.quiet,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
