from __future__ import annotations

import struct

from fastapi import FastAPI
from fastapi.testclient import TestClient


def build_client():
    from routers import tiles_v1

    app = FastAPI()
    app.include_router(tiles_v1.router)
    return tiles_v1, TestClient(app)


def test_elevation_batch_endpoint_returns_fixed_pack(monkeypatch):
    tiles_v1, client = build_client()

    tile_a = b"A" * tiles_v1.ELEVATION_TILE_BYTE_LENGTH
    tile_b = b"B" * tiles_v1.ELEVATION_TILE_BYTE_LENGTH

    async def fake_load_precompressed(z: int, x: int, y: int):
        if (z, x, y) == (7, 21, 45):
            return tile_a, False
        if (z, x, y) == (7, 20, 45):
            return tile_b, False
        raise AssertionError(f"Unexpected tile request: {(z, x, y)}")

    monkeypatch.setattr(
        tiles_v1, "load_precompressed_elevation_tile_bytes", fake_load_precompressed
    )

    response = client.post(
        "/api/v1/tiles/elevation-batch.u16?method=precompressed",
        json={
            "tiles": [
                {"z": 7, "x": 21, "y": 45},
                {"z": 7, "x": 20, "y": 45},
            ]
        },
        headers={"Accept-Encoding": "identity"},
    )

    assert response.status_code == 200
    assert response.headers["X-Tile-Source"] == "elevation-batch"
    assert response.headers["X-Batch-Method"] == "precompressed"
    assert response.headers["X-Tile-Count"] == "2"

    payload = response.content
    assert payload[:4] == tiles_v1.ELEVATION_BATCH_MAGIC
    assert payload[4] == tiles_v1.ELEVATION_BATCH_VERSION

    tile_count = struct.unpack_from("<H", payload, 5)[0]
    assert tile_count == 2

    first_tile = struct.unpack_from("<BHH", payload, 7)
    second_tile = struct.unpack_from("<BHH", payload, 12)
    assert first_tile == (7, 21, 45)
    assert second_tile == (7, 20, 45)

    header_length = 7 + (tile_count * 5)
    tile_length = tiles_v1.ELEVATION_TILE_BYTE_LENGTH
    assert payload[header_length : header_length + tile_length] == tile_a
    assert (
        payload[header_length + tile_length : header_length + (tile_length * 2)]
        == tile_b
    )


def test_elevation_batch_endpoint_short_cache_on_precompressed_miss(monkeypatch):
    tiles_v1, client = build_client()

    async def fake_load_precompressed(z: int, x: int, y: int):
        return tiles_v1._NODATA_TILE_BYTES, True

    monkeypatch.setattr(
        tiles_v1, "load_precompressed_elevation_tile_bytes", fake_load_precompressed
    )

    response = client.post(
        "/api/v1/tiles/elevation-batch.u16?method=precompressed",
        json={"tiles": [{"z": 7, "x": 21, "y": 45}]},
        headers={"Accept-Encoding": "identity"},
    )

    assert response.status_code == 200
    assert response.headers["X-Precompressed-Miss-Count"] == "1"

    cache_control = response.headers.get("Cache-Control", "")
    assert "immutable" not in cache_control.lower()

    from config import IS_DEVELOPMENT

    if IS_DEVELOPMENT:
        assert "no-store" in cache_control.lower()
    else:
        assert "max-age=3600" in cache_control.replace(" ", "")
