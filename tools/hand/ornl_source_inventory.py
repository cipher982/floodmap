#!/usr/bin/env python3
"""Inventory locally downloaded ORNL CFIM HUC6 source ZIPs."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_SOURCE_ROOTS = (
    Path("/mnt/storage/floodmap/data/hand-precomputed/ornl-cfim-v0.21/source-zips"),
    Path("/home/drose/floodmap-data/hand-precomputed/ornl-cfim-v0.21/source-zips"),
)
DEFAULT_EXPECTED_COUNT = 331
DEFAULT_EXPECTED_BYTES = 4_224_140_860_297


@dataclass(frozen=True)
class SourceZipEntry:
    huc: str | None
    path: str
    bytes: int
    valid_name: bool


def huc_from_zip_name(path: Path) -> str | None:
    if path.suffix.lower() != ".zip":
        return None
    stem = path.stem
    if len(stem) == 6 and stem.isdigit():
        return stem
    return None


def iter_source_zip_entries(roots: Iterable[Path]) -> list[SourceZipEntry]:
    entries: list[SourceZipEntry] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.zip")):
            huc = huc_from_zip_name(path)
            entries.append(
                SourceZipEntry(
                    huc=huc,
                    path=str(path),
                    bytes=path.stat().st_size,
                    valid_name=huc is not None,
                )
            )
    return entries


def summarize_inventory(
    entries: Iterable[SourceZipEntry],
    *,
    roots: Iterable[Path],
    expected_count: int | None,
    expected_bytes: int | None,
) -> dict[str, Any]:
    entry_list = list(entries)
    valid_entries = [entry for entry in entry_list if entry.valid_name and entry.huc]
    bytes_downloaded = sum(entry.bytes for entry in entry_list)

    by_huc: dict[str, list[SourceZipEntry]] = defaultdict(list)
    for entry in valid_entries:
        by_huc[entry.huc or ""].append(entry)

    duplicate_hucs = {
        huc: [item.path for item in items]
        for huc, items in sorted(by_huc.items())
        if len(items) > 1
    }
    invalid_entries = [asdict(entry) for entry in entry_list if not entry.valid_name]

    summary: dict[str, Any] = {
        "roots": [str(root) for root in roots],
        "zip_count": len(entry_list),
        "valid_huc_count": len(by_huc),
        "bytes_downloaded": bytes_downloaded,
        "duplicate_hucs": duplicate_hucs,
        "invalid_entries": invalid_entries,
        "entries": [
            asdict(entry) for entry in sorted(entry_list, key=lambda item: item.path)
        ],
    }

    if expected_count is not None:
        summary["expected_count"] = expected_count
        summary["remaining_count"] = max(0, expected_count - len(by_huc))
        summary["count_fraction"] = (
            len(by_huc) / expected_count if expected_count else None
        )

    if expected_bytes is not None:
        summary["expected_bytes"] = expected_bytes
        summary["remaining_bytes_estimate"] = max(0, expected_bytes - bytes_downloaded)
        summary["bytes_fraction"] = (
            bytes_downloaded / expected_bytes if expected_bytes else None
        )

    return summary


def format_text(summary: dict[str, Any]) -> str:
    lines = [
        f"Source roots: {', '.join(summary['roots'])}",
        f"ZIP files: {summary['zip_count']}",
        f"Unique valid HUC6 ZIPs: {summary['valid_huc_count']}",
        f"Bytes downloaded: {summary['bytes_downloaded']:,}",
    ]
    if "expected_count" in summary:
        lines.append(
            f"Count progress: {summary['valid_huc_count']}/{summary['expected_count']} "
            f"({summary['count_fraction']:.2%})"
        )
    if "expected_bytes" in summary:
        lines.append(
            f"Byte progress: {summary['bytes_downloaded']:,}/{summary['expected_bytes']:,} "
            f"({summary['bytes_fraction']:.2%})"
        )
        lines.append(
            f"Remaining bytes estimate: {summary['remaining_bytes_estimate']:,}"
        )
    if summary["duplicate_hucs"]:
        lines.append(f"Duplicate HUCs: {len(summary['duplicate_hucs'])}")
    if summary["invalid_entries"]:
        lines.append(f"Invalid ZIP names: {len(summary['invalid_entries'])}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        action="append",
        dest="source_roots",
        help="Directory containing ORNL HUC6 ZIPs. May be repeated.",
    )
    parser.add_argument("--expected-count", type=int, default=DEFAULT_EXPECTED_COUNT)
    parser.add_argument("--expected-bytes", type=int, default=DEFAULT_EXPECTED_BYTES)
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    roots = tuple(args.source_roots or DEFAULT_SOURCE_ROOTS)
    entries = iter_source_zip_entries(roots)
    summary = summarize_inventory(
        entries,
        roots=roots,
        expected_count=args.expected_count,
        expected_bytes=args.expected_bytes,
    )
    if args.format == "json":
        print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    else:
        print(format_text(summary), flush=True)


if __name__ == "__main__":
    main()
