#!/usr/bin/env python3
"""Incrementally ingest locally downloaded ORNL CFIM HUC6 ZIPs."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.hand.build_ornl_combined_manifest import (
    build_combined_manifest,
    validate_huc,
)
from tools.hand.ingest_ornl_pilot import (
    DEFAULT_DATA_ROOT,
    DEFAULT_SCRATCH_ROOT,
    DEFAULT_SOURCE_ROOTS,
)
from tools.hand.ornl_source_inventory import (
    SourceZipEntry,
    iter_source_zip_entries,
)

ORNL_MANIFEST_PREFIX = "ornl-cfim-v0p21"


@dataclass(frozen=True)
class PlannedHuc:
    huc: str
    archive: str
    archive_bytes: int
    status: str


def huc_manifest_path(manifest_root: Path, huc: str) -> Path:
    return manifest_root / f"{ORNL_MANIFEST_PREFIX}-{validate_huc(huc)}.json"


def converted_hucs(manifest_root: Path) -> set[str]:
    if not manifest_root.exists():
        return set()
    hucs: set[str] = set()
    for path in manifest_root.glob(f"{ORNL_MANIFEST_PREFIX}-*.json"):
        huc = path.stem.removeprefix(f"{ORNL_MANIFEST_PREFIX}-")
        if len(huc) == 6 and huc.isdigit():
            hucs.add(huc)
    return hucs


def cog_path_from_manifest(manifest_path: Path) -> Path | None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    regions = manifest.get("layers", {}).get("hand", {}).get("regions") or []
    if len(regions) != 1:
        return None
    url = regions[0].get("url")
    return Path(url) if isinstance(url, str) else None


def existing_conversion_ready(manifest_root: Path, huc: str, *, verify: bool) -> bool:
    manifest_path = huc_manifest_path(manifest_root, huc)
    if not manifest_path.exists():
        return False
    if not verify:
        return True

    cog_path = cog_path_from_manifest(manifest_path)
    if cog_path is None or not cog_path.exists():
        return False

    import rasterio

    try:
        with rasterio.open(cog_path) as dataset:
            return (
                dataset.count == 1
                and dataset.dtypes[0] == "uint16"
                and dataset.nodata == 65535
                and dataset.width > 0
                and dataset.height > 0
            )
    except Exception:
        return False


def preferred_archives(entries: list[SourceZipEntry]) -> dict[str, SourceZipEntry]:
    archives: dict[str, SourceZipEntry] = {}
    for entry in entries:
        if not entry.huc or not entry.valid_name or entry.bytes <= 0:
            continue
        existing = archives.get(entry.huc)
        if existing is None or entry.bytes > existing.bytes:
            archives[entry.huc] = entry
    return dict(sorted(archives.items()))


def archive_readiness(entry: SourceZipEntry, *, crc_check: bool = False) -> str | None:
    if not entry.huc:
        return "invalid HUC name"
    try:
        with zipfile.ZipFile(entry.path) as archive:
            archive.getinfo(f"{entry.huc}/{entry.huc}hand.tif")
            archive.getinfo(f"{entry.huc}/{entry.huc}.tif")
            if crc_check:
                bad_member = archive.testzip()
                if bad_member is not None:
                    return f"CRC check failed for {bad_member}"
    except Exception as exc:
        return str(exc)
    return None


def filter_ready_archives(
    archives: dict[str, SourceZipEntry],
    *,
    crc_check: bool = False,
) -> tuple[dict[str, SourceZipEntry], list[dict[str, str]]]:
    ready: dict[str, SourceZipEntry] = {}
    not_ready: list[dict[str, str]] = []
    for huc, entry in archives.items():
        reason = archive_readiness(entry, crc_check=crc_check)
        if reason is None:
            ready[huc] = entry
        else:
            not_ready.append({"huc": huc, "archive": entry.path, "reason": reason})
    return ready, not_ready


def normalize_requested_hucs(hucs: list[str] | None) -> list[str] | None:
    if not hucs:
        return None
    normalized: list[str] = []
    seen = set()
    for huc in hucs:
        validated = validate_huc(huc)
        if validated not in seen:
            normalized.append(validated)
            seen.add(validated)
    return normalized


def plan_downloaded_ingest(
    *,
    archives: dict[str, SourceZipEntry],
    manifest_root: Path,
    hucs: list[str] | None,
    huc_prefix: str | None,
    start_after: str | None,
    limit: int | None,
    force: bool,
    verify_existing: bool,
) -> tuple[list[PlannedHuc], list[str]]:
    requested = normalize_requested_hucs(hucs)
    available_hucs = requested or sorted(archives)
    missing_requested: list[str] = []
    planned: list[PlannedHuc] = []

    if huc_prefix is not None and not huc_prefix.isdigit():
        raise ValueError("--huc-prefix must contain only digits")
    if start_after is not None:
        start_after = validate_huc(start_after)

    for huc in available_hucs:
        if huc_prefix is not None and not huc.startswith(huc_prefix):
            continue
        if start_after is not None and huc <= start_after:
            continue
        archive = archives.get(huc)
        if archive is None:
            if requested:
                missing_requested.append(huc)
            continue
        if not force and existing_conversion_ready(
            manifest_root,
            huc,
            verify=verify_existing,
        ):
            continue
        planned.append(
            PlannedHuc(
                huc=huc,
                archive=archive.path,
                archive_bytes=archive.bytes,
                status="planned",
            )
        )
        if limit is not None and len(planned) >= limit:
            break

    return planned, missing_requested


def write_progress_event(progress_jsonl: Path | None, event: dict[str, Any]) -> None:
    if progress_jsonl is None:
        return
    payload = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        **event,
    }
    progress_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with progress_jsonl.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, sort_keys=True) + "\n")


def run_ingest_plan(
    *,
    planned: list[PlannedHuc],
    data_root: Path,
    scratch_root: Path,
    report_root: Path,
    retrieved_at: str,
    chunk_rows: int,
    force: bool,
    skip_archive_hash: bool,
    quiet: bool,
    dry_run: bool,
    continue_on_error: bool,
    keep_extracted_sources: bool,
    progress_jsonl: Path | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    completed: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    if dry_run:
        return completed, failed

    from tools.hand.ingest_ornl_huc6 import default_paths, ingest_ornl_huc6

    for item in planned:
        write_progress_event(
            progress_jsonl,
            {"event": "start", "huc": item.huc, "archive": item.archive},
        )
        try:
            paths = default_paths(
                huc=item.huc,
                archive=Path(item.archive),
                data_root=data_root,
                scratch_root=scratch_root,
                report_root=report_root,
            )
            result = ingest_ornl_huc6(
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
            metrics = result.get("metrics", {})
            if not keep_extracted_sources:
                paths.source_hand.unlink(missing_ok=True)
                paths.source_elevation.unlink(missing_ok=True)
            completed_item = {
                "huc": item.huc,
                "archive": item.archive,
                "manifest": str(paths.manifest_path),
                "output_cog": str(paths.output_cog),
                "output_cog_bytes": paths.output_cog.stat().st_size,
                "valid_fraction": metrics.get("summary", {}).get("valid_fraction"),
            }
            completed.append(completed_item)
            write_progress_event(
                progress_jsonl,
                {"event": "completed", **completed_item},
            )
        except Exception as exc:
            failed_item = {"huc": item.huc, "archive": item.archive, "error": str(exc)}
            failed.append(failed_item)
            write_progress_event(
                progress_jsonl,
                {"event": "failed", **failed_item},
            )
            if not continue_on_error:
                break
    return completed, failed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--huc", action="append", help="Specific HUC6 to ingest.")
    parser.add_argument("--huc-prefix", help="Only ingest HUCs with this prefix.")
    parser.add_argument(
        "--start-after", help="Only ingest HUCs greater than this HUC6."
    )
    parser.add_argument("--limit", type=int, help="Maximum HUCs to ingest in this run.")
    parser.add_argument("--source-root", type=Path, action="append")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--scratch-root", type=Path, default=DEFAULT_SCRATCH_ROOT)
    parser.add_argument(
        "--report-root", type=Path, default=Path("docs/qa/hand-precomputed")
    )
    parser.add_argument("--manifest-root", type=Path)
    parser.add_argument("--retrieved-at", default=date.today().isoformat())
    parser.add_argument("--chunk-rows", type=int, default=512)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-archive-hash", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument(
        "--crc-check",
        action="store_true",
        help="Run ZIP CRC validation before considering archives ready.",
    )
    parser.add_argument(
        "--verify-existing",
        action="store_true",
        help="Open existing COGs with rasterio before skipping converted HUCs.",
    )
    parser.add_argument(
        "--keep-extracted-sources",
        action="store_true",
        help="Keep extracted ORNL float rasters after COG conversion.",
    )
    parser.add_argument(
        "--progress-jsonl",
        type=Path,
        help="Append per-HUC progress events to this JSONL file.",
    )
    parser.add_argument(
        "--allow-incomplete-archives",
        action="store_true",
        help="Do not preflight ZIP central directory and expected ORNL members.",
    )
    parser.add_argument(
        "--combined-output",
        type=Path,
        help="Optional combined manifest to write after successful ingests.",
    )
    parser.add_argument(
        "--combined-dataset-version",
        default="ornl-cfim-v0p21-downloaded",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be >= 1")

    source_roots = args.source_root or DEFAULT_SOURCE_ROOTS
    manifest_root = args.manifest_root or args.data_root / "terrain" / "manifests"
    entries = iter_source_zip_entries(source_roots)
    archives = preferred_archives(entries)
    not_ready: list[dict[str, str]] = []
    if not args.allow_incomplete_archives:
        archives, not_ready = filter_ready_archives(
            archives,
            crc_check=args.crc_check,
        )
    planned, missing_requested = plan_downloaded_ingest(
        archives=archives,
        manifest_root=manifest_root,
        hucs=args.huc,
        huc_prefix=args.huc_prefix,
        start_after=args.start_after,
        limit=args.limit,
        force=args.force,
        verify_existing=args.verify_existing,
    )
    completed, failed = run_ingest_plan(
        planned=planned,
        data_root=args.data_root,
        scratch_root=args.scratch_root,
        report_root=args.report_root,
        retrieved_at=args.retrieved_at,
        chunk_rows=args.chunk_rows,
        force=args.force,
        skip_archive_hash=args.skip_archive_hash,
        quiet=args.quiet,
        dry_run=args.dry_run,
        continue_on_error=args.continue_on_error,
        keep_extracted_sources=args.keep_extracted_sources,
        progress_jsonl=args.progress_jsonl,
    )

    combined_manifest = None
    if args.combined_output and not args.dry_run:
        hucs = sorted(converted_hucs(manifest_root))
        manifest = build_combined_manifest(
            hucs=hucs,
            manifest_root=manifest_root,
            dataset_version=args.combined_dataset_version,
        )
        args.combined_output.parent.mkdir(parents=True, exist_ok=True)
        args.combined_output.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        combined_manifest = {
            "output": str(args.combined_output),
            "region_count": len(manifest["layers"]["hand"]["regions"]),
        }

    result = {
        "source_roots": [str(root) for root in source_roots],
        "available_huc_count": len(archives),
        "planned_count": len(planned),
        "completed_count": len(completed),
        "failed_count": len(failed),
        "missing_requested": missing_requested,
        "not_ready": not_ready,
        "not_ready_count": len(not_ready),
        "planned": [asdict(item) for item in planned],
        "completed": completed,
        "failed": failed,
        "combined_manifest": combined_manifest,
        "dry_run": args.dry_run,
    }
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)

    if failed and not args.continue_on_error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
