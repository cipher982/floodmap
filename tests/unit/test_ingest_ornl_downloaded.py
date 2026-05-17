from __future__ import annotations

import json
import zipfile

from tools.hand.ingest_ornl_downloaded import (
    archive_readiness,
    converted_hucs,
    existing_conversion_ready,
    filter_ready_archives,
    plan_downloaded_ingest,
    preferred_archives,
    write_progress_event,
)
from tools.hand.ornl_source_inventory import SourceZipEntry


def write_manifest(root, huc: str, cog_path: str | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"ornl-cfim-v0p21-{huc}.json").write_text(
        json.dumps(
            {
                "dataset_version": f"ornl-cfim-v0p21-{huc}",
                "layers": {
                    "hand": {
                        "regions": [
                            {
                                "url": cog_path or f"/data/{huc}.tif",
                            }
                        ]
                    }
                },
            }
        ),
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


def test_archive_readiness_checks_expected_ornl_members(tmp_path) -> None:
    good_zip = tmp_path / "031601.zip"
    with zipfile.ZipFile(good_zip, "w") as archive:
        archive.writestr("031601/031601hand.tif", b"hand")
        archive.writestr("031601/031601.tif", b"elevation")
    bad_zip = tmp_path / "031502.zip"
    bad_zip.write_bytes(b"partial")

    good = SourceZipEntry(
        huc="031601", path=str(good_zip), bytes=good_zip.stat().st_size, valid_name=True
    )
    bad = SourceZipEntry(
        huc="031502", path=str(bad_zip), bytes=bad_zip.stat().st_size, valid_name=True
    )

    assert archive_readiness(good) is None
    assert "zip" in archive_readiness(bad).lower()

    ready, not_ready = filter_ready_archives({"031601": good, "031502": bad})
    assert list(ready) == ["031601"]
    assert not_ready[0]["huc"] == "031502"


def test_existing_conversion_ready_checks_manifest_without_rasterio(tmp_path) -> None:
    write_manifest(tmp_path, "031601")

    assert existing_conversion_ready(tmp_path, "031601", verify=False) is True
    assert existing_conversion_ready(tmp_path, "031601", verify=True) is False
    assert existing_conversion_ready(tmp_path, "031502", verify=False) is False


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
        verify_existing=False,
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
        verify_existing=False,
    )

    assert [item.huc for item in planned] == ["031601"]
    assert missing == ["031502"]


def test_write_progress_event_appends_jsonl(tmp_path) -> None:
    progress = tmp_path / "progress.jsonl"

    write_progress_event(progress, {"event": "completed", "huc": "031601"})
    write_progress_event(progress, {"event": "failed", "huc": "031502"})

    lines = [
        json.loads(line) for line in progress.read_text(encoding="utf-8").splitlines()
    ]
    assert [line["event"] for line in lines] == ["completed", "failed"]
    assert lines[0]["huc"] == "031601"
    assert "ts" in lines[0]
