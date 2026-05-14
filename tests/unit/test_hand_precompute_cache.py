from __future__ import annotations

import importlib.util
from pathlib import Path


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


def test_filter_tiles_by_shard_splits_by_tile_column():
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

    assert shard_0 == [(12, 0, 0), (12, 2, 0), (12, 4, 0)]
    assert shard_1 == [(12, 1, 0), (12, 3, 0)]
    assert sorted(shard_0 + shard_1) == tiles
