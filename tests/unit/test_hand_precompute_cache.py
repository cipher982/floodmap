from __future__ import annotations

import importlib.util
from argparse import Namespace
from pathlib import Path

import numpy as np
from terrain import (
    TILE_SIZE,
    TerrainEncoding,
    TerrainLayer,
    TerrainManifest,
    TerrainRegion,
)


def load_precompute_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "hand"
        / "precompute_terrain_cache.py"
    )
    spec = importlib.util.spec_from_file_location("precompute_terrain_cache", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_iter_tiles_for_bbox_matches_birmingham_prototype_counts():
    module = load_precompute_module()
    bbox = (-87.02, 33.30, -86.52, 33.75)

    tiles = module.iter_tiles_for_bbox(bbox, min_zoom=9, max_zoom=12)

    counts = {z: sum(1 for tile in tiles if tile[0] == z) for z in range(9, 13)}
    assert counts == {9: 2, 10: 6, 11: 16, 12: 49}


def test_iter_tiles_for_bbox_respects_zoom_limits():
    module = load_precompute_module()
    bbox = (-87.02, 33.30, -86.52, 33.75)

    tiles = module.iter_tiles_for_bbox(bbox, min_zoom=12, max_zoom=12)

    assert tiles
    assert {tile[0] for tile in tiles} == {12}


def test_filter_tiles_by_shard_partitions_tiles_by_hash():
    module = load_precompute_module()
    tiles = [
        (12, 0, 0),
        (12, 1, 0),
        (12, 2, 0),
        (12, 3, 0),
        (12, 4, 0),
    ]

    shard_0 = module.filter_tiles_by_shard(tiles, shard_index=0, shard_count=2)
    shard_1 = module.filter_tiles_by_shard(tiles, shard_index=1, shard_count=2)

    assert sorted(shard_0 + shard_1) == tiles
    assert not set(shard_0).intersection(shard_1)
    assert all(module.tile_shard_index(tile, 2) == 0 for tile in shard_0)
    assert all(module.tile_shard_index(tile, 2) == 1 for tile in shard_1)


def test_precompute_region_supports_threaded_workers(tmp_path, monkeypatch):
    module = load_precompute_module()
    source_path = tmp_path / "source.tif"
    source_path.write_bytes(b"source")
    manifest = TerrainManifest(
        dataset_version="hand-test",
        layers={
            "hand": TerrainLayer(
                encoding=TerrainEncoding.HAND_DECIMETERS,
                regions=[
                    TerrainRegion(
                        id="test-region",
                        bbox=(-87.02, 33.30, -86.52, 33.75),
                        crs="EPSG:5070",
                        url=str(source_path),
                    )
                ],
            )
        },
    )
    args = Namespace(
        layer="hand",
        region_id="test-region",
        min_zoom=12,
        max_zoom=12,
        cache_dir=tmp_path / "cache",
        limit=8,
        overwrite=False,
        dry_run=False,
        workers=4,
        shard_index=0,
        shard_count=1,
        skip_empty=False,
    )

    def fake_render(_source_path, z, x, y):
        values = np.full((TILE_SIZE, TILE_SIZE), (z + x + y) % 100, dtype=np.uint16)
        return values.tobytes(), "MISS", 1.5

    monkeypatch.setattr(module, "get_terrain_manifest", lambda: manifest)
    monkeypatch.setattr(
        module, "require_region_source_path", lambda *_args: source_path
    )
    monkeypatch.setattr(module, "render_cog_tile_with_cache", fake_render)

    stats = module.precompute_region(args)

    assert stats["candidate_tiles"] == 8
    assert stats["written"] == 8
    assert stats["existing"] == 0
    assert stats["cache_tiles_total"] == 8
