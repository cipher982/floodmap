"""Terrain source manifest loading helpers."""

from __future__ import annotations

from pathlib import Path

from terrain import TerrainEncoding, TerrainLayer, TerrainManifest, TerrainRegion

BIRMINGHAM_HAND_BBOX = (-87.02, 33.30, -86.52, 33.75)


def build_builtin_hand_manifest(
    *,
    dataset_version: str,
    source_path: Path,
    region_id: str = "birmingham-prototype",
    bbox: tuple[float, float, float, float] = BIRMINGHAM_HAND_BBOX,
    crs: str = "EPSG:5070",
) -> TerrainManifest:
    return TerrainManifest(
        schema_version=1,
        dataset_version=dataset_version,
        layers={
            "hand": TerrainLayer(
                encoding=TerrainEncoding.HAND_DECIMETERS,
                regions=[
                    TerrainRegion(
                        id=region_id,
                        bbox=bbox,
                        crs=crs,
                        url=str(source_path),
                    )
                ],
            )
        },
    )


def load_terrain_manifest_from_path(path: Path | None) -> TerrainManifest | None:
    if path is None or not path.exists():
        return None
    return TerrainManifest.model_validate_json(path.read_text(encoding="utf-8"))


def hand_route_context_from_manifest(
    manifest: TerrainManifest, *, enabled: bool
) -> dict[str, object]:
    hand_layer = manifest.layers.get("hand")
    regions = hand_layer.regions if hand_layer is not None else []
    coverage_label = (
        regions[0].id.replace("-", " ").title()
        if len(regions) == 1
        else f"{len(regions)} regions"
    )
    return {
        "terrainLayers": {
            "hand": {
                "enabled": enabled and hand_layer is not None,
                "datasetVersion": manifest.dataset_version,
                "label": "Drainage",
                "coverageLabel": coverage_label,
            }
        }
    }
