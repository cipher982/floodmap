from __future__ import annotations

import json

from terrain_manifest import (
    build_builtin_hand_manifest,
    hand_route_context_from_manifest,
    load_terrain_manifest_from_path,
)


def test_load_terrain_manifest_from_path_reads_versioned_regions(tmp_path):
    path = tmp_path / "terrain-manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset_version": "hand-test",
                "layers": {
                    "hand": {
                        "encoding": "uint16-decimeters",
                        "nodata": 65535,
                        "regions": [
                            {
                                "id": "region-a",
                                "bbox": [-87.0, 33.0, -86.5, 33.5],
                                "crs": "EPSG:5070",
                                "url": "file://region-a.tif",
                            },
                            {
                                "id": "region-b",
                                "bbox": [-96.0, 29.0, -95.0, 30.0],
                                "crs": "EPSG:5070",
                                "url": "file://region-b.tif",
                            },
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    manifest = load_terrain_manifest_from_path(path)

    assert manifest is not None
    assert manifest.dataset_version == "hand-test"
    assert [region.id for region in manifest.layers["hand"].regions] == [
        "region-a",
        "region-b",
    ]


def test_hand_route_context_reports_manifest_dataset_and_coverage(tmp_path):
    manifest = build_builtin_hand_manifest(
        dataset_version="hand-test",
        source_path=tmp_path / "hand.tif",
        region_id="birmingham-prototype",
    )

    context = hand_route_context_from_manifest(manifest, enabled=True)

    assert context["terrainLayers"]["hand"]["enabled"] is True
    assert context["terrainLayers"]["hand"]["datasetVersion"] == "hand-test"
    assert context["terrainLayers"]["hand"]["coverageLabel"] == "Birmingham Prototype"
