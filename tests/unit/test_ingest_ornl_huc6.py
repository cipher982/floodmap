from __future__ import annotations

import zipfile

import pytest

from tools.hand.ingest_ornl_huc6 import (
    default_paths,
    extract_ornl_inputs,
    source_metadata,
    validate_huc,
)


def test_default_paths_are_cube_layout(tmp_path) -> None:
    paths = default_paths(
        huc="031601",
        archive=None,
        data_root=tmp_path / "data",
        scratch_root=tmp_path / "scratch",
        report_root=tmp_path / "reports",
    )

    assert paths.archive == (
        tmp_path
        / "data"
        / "hand-precomputed"
        / "ornl-cfim-v0.21"
        / "031601"
        / "031601.zip"
    )
    assert paths.source_hand.name == "031601hand.tif"
    assert paths.source_elevation.name == "031601-elevation.tif"
    assert paths.output_cog.name == "031601hand-u16dm.cog.tif"
    assert paths.manifest_path.name == "ornl-cfim-v0p21-031601.json"
    assert paths.dataset_version == "ornl-cfim-v0p21-031601"
    assert paths.region_id == "ornl-cfim-v0p21-huc6-031601"


@pytest.mark.parametrize("huc", ["31601", "0316012", "abcdef"])
def test_validate_huc_rejects_non_huc6(huc: str) -> None:
    with pytest.raises(ValueError):
        validate_huc(huc)


def test_extract_ornl_inputs_flattens_zip_members(tmp_path) -> None:
    archive = tmp_path / "031601.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("031601/031601hand.tif", b"hand")
        zip_file.writestr("031601/031601.tif", b"elevation")

    paths = default_paths(
        huc="031601",
        archive=archive,
        data_root=tmp_path / "data",
        scratch_root=tmp_path / "scratch",
        report_root=tmp_path / "reports",
    )

    result = extract_ornl_inputs(paths, force=False)
    second_result = extract_ornl_inputs(paths, force=False)

    assert paths.source_hand.read_bytes() == b"hand"
    assert paths.source_elevation.read_bytes() == b"elevation"
    assert result["hand_member"] == "031601/031601hand.tif"
    assert result["elevation_member"] == "031601/031601.tif"
    assert result["extracted_hand"] is True
    assert result["extracted_elevation"] is True
    assert second_result["extracted_hand"] is False
    assert second_result["extracted_elevation"] is False


def test_source_metadata_records_ornl_provenance() -> None:
    metadata = source_metadata("031601", "2026-05-15")

    assert metadata["name"] == "ORNL CFIM v0.21"
    assert metadata["huc"] == "031601"
    assert metadata["retrieved_at"] == "2026-05-15"
    assert "10.13139/ORNLNCCS/1630903" in metadata["citation"]
