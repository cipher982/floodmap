from __future__ import annotations

import json

import pytest

from tools.hand.ingest_ornl_pilot import (
    build_pilot_manifest,
    find_huc_archive,
    normalize_hucs,
)


def write_huc_manifest(root, huc: str) -> None:
    (root / f"ornl-cfim-v0p21-{huc}.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset_version": f"ornl-cfim-v0p21-{huc}",
                "layers": {
                    "hand": {
                        "encoding": "uint16-decimeters",
                        "nodata": 65535,
                        "regions": [
                            {
                                "id": f"ornl-cfim-v0p21-huc6-{huc}",
                                "bbox": [-89, 32, -86, 35],
                                "crs": "EPSG:4269",
                                "url": f"/data/{huc}.tif",
                            }
                        ],
                    }
                },
                "source": {"name": "ORNL CFIM v0.21", "huc": huc},
            }
        ),
        encoding="utf-8",
    )


def test_normalize_hucs_dedupes_in_order() -> None:
    assert normalize_hucs(["031601", "031502", "031601"]) == ["031601", "031502"]


@pytest.mark.parametrize("huc", ["03160", "0316012", "abc123"])
def test_normalize_hucs_rejects_invalid_codes(huc: str) -> None:
    with pytest.raises(ValueError):
        normalize_hucs([huc])


def test_find_huc_archive_uses_first_existing_nonempty_zip(tmp_path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "031601.zip").write_bytes(b"")
    (second / "031601.zip").write_bytes(b"zip")

    assert find_huc_archive("031601", [first, second]) == second / "031601.zip"


def test_build_pilot_manifest_allows_missing_hucs(tmp_path) -> None:
    manifest_root = tmp_path / "manifests"
    manifest_root.mkdir()
    write_huc_manifest(manifest_root, "031601")

    result = build_pilot_manifest(
        hucs=["031601", "031502"],
        source_roots=[tmp_path / "sources"],
        data_root=tmp_path / "data",
        scratch_root=tmp_path / "scratch",
        report_root=tmp_path / "reports",
        manifest_root=manifest_root,
        output=tmp_path / "combined.json",
        dataset_version="ornl-cfim-v0p21-test",
        retrieved_at="2026-05-15",
        chunk_rows=512,
        force=False,
        allow_missing=True,
        skip_archive_hash=True,
        quiet=True,
        dry_run=False,
    )

    assert result["included_hucs"] == ["031601"]
    assert result["missing_hucs"] == ["031502"]
    assert result["manifest_region_count"] == 1
    assert (tmp_path / "combined.json").exists()


def test_build_pilot_manifest_fails_when_required_huc_missing(tmp_path) -> None:
    manifest_root = tmp_path / "manifests"
    manifest_root.mkdir()
    write_huc_manifest(manifest_root, "031601")

    with pytest.raises(SystemExit, match="031502"):
        build_pilot_manifest(
            hucs=["031601", "031502"],
            source_roots=[tmp_path / "sources"],
            data_root=tmp_path / "data",
            scratch_root=tmp_path / "scratch",
            report_root=tmp_path / "reports",
            manifest_root=manifest_root,
            output=tmp_path / "combined.json",
            dataset_version="ornl-cfim-v0p21-test",
            retrieved_at="2026-05-15",
            chunk_rows=512,
            force=False,
            allow_missing=False,
            skip_archive_hash=True,
            quiet=True,
            dry_run=False,
        )
