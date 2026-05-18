from __future__ import annotations

import json

import pytest

from tools.hand.build_ornl_combined_manifest import (
    build_combined_manifest,
    validate_huc,
)


def write_huc_manifest(root, huc: str, bbox: list[float]) -> None:
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
                                "bbox": bbox,
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


def test_build_combined_manifest_preserves_huc_order(tmp_path) -> None:
    write_huc_manifest(tmp_path, "031601", [-89, 32, -86, 35])
    write_huc_manifest(tmp_path, "031501", [-87, 32, -84, 35])

    manifest = build_combined_manifest(
        hucs=["031601", "031501"],
        manifest_root=tmp_path,
        dataset_version="ornl-cfim-v0p21-central-alabama",
    )

    regions = manifest["layers"]["hand"]["regions"]
    assert manifest["dataset_version"] == "ornl-cfim-v0p21-central-alabama"
    assert [region["id"] for region in regions] == [
        "ornl-cfim-v0p21-huc6-031601",
        "ornl-cfim-v0p21-huc6-031501",
    ]
    assert manifest["source"]["components"] == [
        {"name": "ORNL CFIM v0.21", "huc": "031601"},
        {"name": "ORNL CFIM v0.21", "huc": "031501"},
    ]


def test_build_combined_manifest_can_include_elevation_layer(tmp_path) -> None:
    write_huc_manifest(tmp_path, "031601", [-89, 32, -86, 35])

    manifest = build_combined_manifest(
        hucs=["031601"],
        manifest_root=tmp_path,
        dataset_version="ornl-cfim-v0p21-central-alabama",
        elevation_data_root=tmp_path / "data",
    )

    elevation_layer = manifest["layers"]["elevation"]
    assert elevation_layer["encoding"] == "elevation-meter-range"
    assert elevation_layer["regions"][0]["url"].endswith(
        "/hand-precomputed/ornl-cfim-v0.21/031601/031601-elevation.tif"
    )
    assert elevation_layer["regions"][0]["bbox"] == [-89, 32, -86, 35]


@pytest.mark.parametrize("huc", ["03160", "0316012", "abcdef"])
def test_validate_huc_rejects_non_huc6(huc: str) -> None:
    with pytest.raises(ValueError):
        validate_huc(huc)
