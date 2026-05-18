#!/usr/bin/env python3
"""Extract ORNL CFIM HUC6 elevation rasters from already-downloaded ZIPs.

The combined ORNL manifest can include an elevation layer that points at:

  DATA_ROOT/hand-precomputed/ornl-cfim-v0.21/<HUC>/<HUC>-elevation.tif

The normal HAND ingest may delete these source rasters after converting HAND to
COG. This tool fills only the elevation backing files without rerunning HAND COG
conversion or extracting bulky intermediate HAND rasters.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.hand.build_ornl_combined_manifest import validate_huc
from tools.hand.ingest_ornl_downloaded import preferred_archives
from tools.hand.ingest_ornl_pilot import DEFAULT_DATA_ROOT, DEFAULT_SOURCE_ROOTS
from tools.hand.ornl_source_inventory import SourceZipEntry, iter_source_zip_entries


@dataclass(frozen=True)
class PlannedElevationExtract:
    huc: str
    archive: str
    member: str
    output: str
    archive_bytes: int
    status: str


def elevation_output_path(data_root: Path, huc: str) -> Path:
    return (
        data_root
        / "hand-precomputed"
        / "ornl-cfim-v0.21"
        / huc
        / f"{huc}-elevation.tif"
    )


def elevation_member_name(archive: zipfile.ZipFile, huc: str) -> str:
    candidates = [f"{huc}/{huc}.tif", f"{huc}.tif"]
    names = set(archive.namelist())
    for candidate in candidates:
        if candidate in names:
            return candidate
    raise KeyError(f"{huc}: elevation member not found")


def normalize_hucs(hucs: list[str] | None) -> list[str] | None:
    if not hucs:
        return None
    seen: set[str] = set()
    normalized: list[str] = []
    for huc in hucs:
        valid = validate_huc(huc)
        if valid not in seen:
            normalized.append(valid)
            seen.add(valid)
    return normalized


def plan_extractions(
    *,
    archives: dict[str, SourceZipEntry],
    data_root: Path,
    hucs: list[str] | None,
    start_after: str | None,
    limit: int | None,
    force: bool,
) -> tuple[list[PlannedElevationExtract], list[str]]:
    requested = normalize_hucs(hucs)
    available = requested or sorted(archives)
    missing: list[str] = []
    planned: list[PlannedElevationExtract] = []
    start_after = validate_huc(start_after) if start_after else None

    for huc in available:
        if start_after is not None and huc <= start_after:
            continue
        entry = archives.get(huc)
        if entry is None:
            if requested:
                missing.append(huc)
            continue
        output = elevation_output_path(data_root, huc)
        if output.exists() and output.stat().st_size > 0 and not force:
            continue
        try:
            with zipfile.ZipFile(entry.path) as archive:
                member = elevation_member_name(archive, huc)
        except Exception:
            member = f"{huc}/{huc}.tif"
        planned.append(
            PlannedElevationExtract(
                huc=huc,
                archive=entry.path,
                member=member,
                output=str(output),
                archive_bytes=entry.bytes,
                status="planned",
            )
        )
        if limit is not None and len(planned) >= limit:
            break
    return planned, missing


def write_progress(progress_jsonl: Path | None, event: dict[str, Any]) -> None:
    if progress_jsonl is None:
        return
    progress_jsonl.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        **event,
    }
    with progress_jsonl.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, sort_keys=True) + "\n")


def extract_one(
    item: PlannedElevationExtract,
    *,
    progress_jsonl: Path | None,
) -> dict[str, Any]:
    output = Path(item.output)
    tmp = output.with_suffix(output.suffix + ".tmp")
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp.unlink(missing_ok=True)
    write_progress(progress_jsonl, {"event": "start", "huc": item.huc})
    with zipfile.ZipFile(item.archive) as archive:
        info = archive.getinfo(item.member)
        with archive.open(info) as source, tmp.open("wb") as destination:
            shutil.copyfileobj(source, destination, length=8 * 1024 * 1024)
    tmp.replace(output)
    result = {
        **asdict(item),
        "status": "completed",
        "output_bytes": output.stat().st_size,
    }
    write_progress(progress_jsonl, {"event": "completed", **result})
    return result


def run_plan(
    planned: list[PlannedElevationExtract],
    *,
    dry_run: bool,
    continue_on_error: bool,
    progress_jsonl: Path | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    completed: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    if dry_run:
        return completed, failed
    for item in planned:
        try:
            completed.append(extract_one(item, progress_jsonl=progress_jsonl))
        except Exception as exc:
            failed_item = {"huc": item.huc, "archive": item.archive, "error": str(exc)}
            failed.append(failed_item)
            write_progress(progress_jsonl, {"event": "failed", **failed_item})
            if not continue_on_error:
                break
    return completed, failed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--huc", action="append", help="Specific HUC6 to extract.")
    parser.add_argument(
        "--start-after", help="Only extract HUCs greater than this HUC6."
    )
    parser.add_argument("--limit", type=int, help="Maximum HUCs to extract.")
    parser.add_argument("--source-root", type=Path, action="append")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--progress-jsonl", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be >= 1")
    source_roots = args.source_root or DEFAULT_SOURCE_ROOTS
    archives = preferred_archives(iter_source_zip_entries(source_roots))
    planned, missing = plan_extractions(
        archives=archives,
        data_root=args.data_root,
        hucs=args.huc,
        start_after=args.start_after,
        limit=args.limit,
        force=args.force,
    )
    completed, failed = run_plan(
        planned,
        dry_run=args.dry_run,
        continue_on_error=args.continue_on_error,
        progress_jsonl=args.progress_jsonl,
    )
    result = {
        "source_roots": [str(root) for root in source_roots],
        "available_huc_count": len(archives),
        "planned_count": len(planned),
        "completed_count": len(completed),
        "failed_count": len(failed),
        "missing_requested": missing,
        "planned": [asdict(item) for item in planned],
        "completed": completed,
        "failed": failed,
        "dry_run": args.dry_run,
    }
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    if failed and not args.continue_on_error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
