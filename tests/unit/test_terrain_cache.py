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
