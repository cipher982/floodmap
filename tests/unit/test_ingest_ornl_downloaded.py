from __future__ import annotations

import json

from tools.hand.ingest_ornl_downloaded import (
    converted_hucs,
    plan_downloaded_ingest,
    preferred_archives,
)
from tools.hand.ornl_source_inventory import SourceZipEntry


def write_manifest(root, huc: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"ornl-cfim-v0p21-{huc}.json").write_text(
        json.dumps({"dataset_version": f"ornl-cfim-v0p21-{huc}"}),
        encoding="utf-8",
    )


def entry(huc: str, path: str, bytes_: int) -> SourceZipEntry:
    return SourceZipEntry(huc=huc, path=path, bytes=bytes_, valid_name=True)


def test_preferred_archives_keeps_largest_duplicate() -> None:
    archives = preferred_archives(
        [
            entry("031601", "/a/031601.zip", 10),
            entry("031601", "/b/031601.zip", 20),
            SourceZipEntry(huc=None, path="/a/bad.zip", bytes=99, valid_name=False),
        ]
    )

    assert archives["031601"].path == "/b/031601.zip"
    assert list(archives) == ["031601"]


def test_converted_hucs_reads_per_huc_manifest_names(tmp_path) -> None:
    write_manifest(tmp_path, "031601")
    (tmp_path / "ornl-cfim-v0p21-southeast-pilot.json").write_text(
        "{}", encoding="utf-8"
    )

    assert converted_hucs(tmp_path) == {"031601"}


def test_plan_downloaded_ingest_skips_converted_and_applies_limit(tmp_path) -> None:
    write_manifest(tmp_path, "031601")
    archives = preferred_archives(
        [
            entry("030101", "/z/030101.zip", 30),
            entry("031501", "/z/031501.zip", 20),
            entry("031601", "/z/031601.zip", 10),
        ]
    )

    planned, missing = plan_downloaded_ingest(
        archives=archives,
        manifest_root=tmp_path,
        hucs=None,
        huc_prefix="03",
        start_after="030101",
        limit=1,
        force=False,
    )

    assert missing == []
    assert [item.huc for item in planned] == ["031501"]


def test_plan_downloaded_ingest_reports_missing_requested_huc(tmp_path) -> None:
    archives = preferred_archives([entry("031601", "/z/031601.zip", 10)])

    planned, missing = plan_downloaded_ingest(
        archives=archives,
        manifest_root=tmp_path,
        hucs=["031601", "031502"],
        huc_prefix=None,
        start_after=None,
        limit=None,
        force=False,
    )

    assert [item.huc for item in planned] == ["031601"]
    assert missing == ["031502"]
