from __future__ import annotations

import gzip

import numpy as np
import pytest
from terrain import U16_TILE_BYTES
from terrain_cache import TerrainTileCache


def test_terrain_cache_writes_brotli_tile_and_serves_identity_or_br(tmp_path):
    cache = TerrainTileCache(tmp_path)
    payload = np.full(U16_TILE_BYTES // 2, 7, dtype=np.uint16).tobytes()

    path = cache.write_tile("hand", "hand-test", 9, 132, 204, payload, "ok")

    assert path.exists()
    assert path.name == "204.u16.br"

    identity = cache.read_tile("hand", "hand-test", 9, 132, 204, "identity")
    assert identity is not None
    assert identity.payload == payload
    assert identity.content_encoding is None
    assert identity.data_status == "ok"

    compressed = cache.read_tile("hand", "hand-test", 9, 132, 204, "br,gzip")
    assert compressed is not None
    assert compressed.payload == path.read_bytes()
    assert compressed.content_encoding == "br"

    stats = cache.stats("hand", "hand-test")
    assert stats.tile_count == 1
    assert stats.compressed_bytes == path.stat().st_size


def test_terrain_cache_recompresses_brotli_tile_for_gzip_client(tmp_path):
    cache = TerrainTileCache(tmp_path)
    payload = np.full(U16_TILE_BYTES // 2, 13, dtype=np.uint16).tobytes()
    cache.write_tile("hand", "hand-test", 9, 132, 204, payload, "source-nodata")

    cached = cache.read_tile("hand", "hand-test", 9, 132, 204, "gzip")

    assert cached is not None
    assert cached.content_encoding == "gzip"
    assert gzip.decompress(cached.payload) == payload
    assert cached.data_status == "source-nodata"


def test_terrain_cache_rejects_wrong_tile_size(tmp_path):
    cache = TerrainTileCache(tmp_path)

    with pytest.raises(ValueError) as exc:
        cache.write_tile("hand", "hand-test", 9, 132, 204, b"short", "ok")

    assert str(U16_TILE_BYTES) in str(exc.value)


def test_terrain_cache_prunes_oldest_tiles_to_size(tmp_path):
    cache = TerrainTileCache(tmp_path)
    payload_a = np.full(U16_TILE_BYTES // 2, 1, dtype=np.uint16).tobytes()
    payload_b = np.arange(U16_TILE_BYTES // 2, dtype=np.uint16).tobytes()
    path_a = cache.write_tile("hand", "hand-test", 9, 132, 204, payload_a, "ok")
    path_b = cache.write_tile("hand", "hand-test", 9, 133, 204, payload_b, "ok")

    max_bytes = path_b.stat().st_size
    result = cache.prune_to_size(max_bytes, "hand", "hand-test")

    assert result.removed_tiles == 1
    assert not path_a.exists()
    assert not cache.meta_path("hand", "hand-test", 9, 132, 204).exists()
    assert path_b.exists()
    assert cache.stats("hand", "hand-test").tile_count == 1


def test_terrain_cache_maybe_prune_is_interval_gated(tmp_path):
    cache = TerrainTileCache(tmp_path)
    payload = np.arange(U16_TILE_BYTES // 2, dtype=np.uint16).tobytes()
    cache.write_tile("hand", "hand-test", 9, 132, 204, payload, "ok")
    cache.write_tile("hand", "hand-test", 9, 133, 204, payload, "ok")

    first = cache.maybe_prune_to_size(1, "hand", "hand-test", min_interval_seconds=60)
    second = cache.maybe_prune_to_size(1, "hand", "hand-test", min_interval_seconds=60)

    assert first is not None
    assert second is None
