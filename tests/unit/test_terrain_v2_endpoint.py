from __future__ import annotations

import inspect
import struct

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import terrain_v2
from terrain import (
    TERRAIN_BATCH_MAGIC,
    TERRAIN_BATCH_TILE_META_BYTES,
    TILE_SIZE,
    U16_TILE_BYTES,
    lonlat_to_tile_pixel,
)
from terrain_cog import tile_transform_mercator

rasterio = pytest.importorskip("rasterio")


@pytest.fixture
def client(tmp_path, monkeypatch):
    source_path = tmp_path / "hand.tif"
    values = np.full((TILE_SIZE, TILE_SIZE), 42, dtype=np.uint16)
    with rasterio.open(
        source_path,
        "w",
        driver="GTiff",
        width=TILE_SIZE,
        height=TILE_SIZE,
        count=1,
        dtype="uint16",
        crs="EPSG:3857",
        transform=tile_transform_mercator(0, 0, 0),
        nodata=65535,
    ) as dataset:
        dataset.write(values, 1)

    monkeypatch.setattr(terrain_v2, "BIRMINGHAM_HAND_COG_PATH", source_path)
    monkeypatch.setattr(terrain_v2, "BIRMINGHAM_HAND_DATASET_VERSION", "hand-test")

    app = FastAPI()
    app.include_router(terrain_v2.router)
    return TestClient(app)


def test_get_terrain_tile_returns_uncompressed_u16_tile(client):
    response = client.get(
        "/api/v2/terrain/hand/hand-test/0/0/0.u16",
        headers={"Accept-Encoding": "identity"},
    )

    assert response.status_code == 200
    assert len(response.content) == U16_TILE_BYTES
    assert response.headers["X-Terrain-Layer"] == "hand"
    assert response.headers["X-Terrain-Dataset-Version"] == "hand-test"
    assert response.headers["X-Terrain-Source"] == "dynamic-cog"
    assert response.headers["X-Terrain-Data-Status"] == "ok"
    assert response.headers["X-Cache"] in {"HIT", "MISS"}
    assert np.frombuffer(response.content, dtype=np.uint16)[0] == 42


def test_get_terrain_tile_can_gzip_response(client):
    response = client.get(
        "/api/v2/terrain/hand/hand-test/0/0/0.u16",
        headers={"Accept-Encoding": "gzip"},
    )

    assert response.status_code == 200
    assert response.headers["Content-Encoding"] == "gzip"
    # TestClient auto-decodes gzip bodies but preserves the response header.
    assert len(response.content) == U16_TILE_BYTES


def test_get_terrain_batch_packs_unique_tiles(client):
    response = client.post(
        "/api/v2/terrain/hand/hand-test/batch.u16",
        headers={"Accept-Encoding": "identity"},
        json={
            "tiles": [
                {"z": 0, "x": 0, "y": 0},
                {"z": 0, "x": 0, "y": 0},
            ]
        },
    )

    assert response.status_code == 200
    assert response.content[:4] == TERRAIN_BATCH_MAGIC
    assert struct.unpack_from("<H", response.content, 5)[0] == 1
    assert struct.unpack_from("<BII", response.content, 7) == (0, 0, 0)
    header_length = 7 + TERRAIN_BATCH_TILE_META_BYTES
    assert len(response.content[header_length:]) == U16_TILE_BYTES
    assert response.headers["X-Tile-Count"] == "1"


def test_terrain_metadata_reports_version_and_templates(client):
    response = client.get("/api/v2/terrain/hand/metadata")

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataset_version"] == "hand-test"
    assert payload["encoding"] == "uint16-decimeters"
    assert payload["tile_template"].endswith("/hand-test/{z}/{x}/{y}.u16")
    assert payload["batch_template"].endswith("/hand-test/batch.u16")


def test_sample_terrain_reads_cog_value(client):
    response = client.get("/api/v2/terrain/hand/sample?lat=33.5207&lng=-86.8025")

    assert response.status_code == 200
    payload = response.json()
    assert payload["height_m"] == 4.2
    assert payload["height_ft"] == 13.8
    assert payload["dataset_version"] == "hand-test"


def test_missing_source_returns_build_miss_headers(tmp_path, monkeypatch):
    monkeypatch.setattr(
        terrain_v2, "BIRMINGHAM_HAND_COG_PATH", tmp_path / "missing.tif"
    )
    monkeypatch.setattr(terrain_v2, "BIRMINGHAM_HAND_DATASET_VERSION", "hand-missing")

    app = FastAPI()
    app.include_router(terrain_v2.router)
    response = TestClient(app).get(
        "/api/v2/terrain/hand/hand-missing/0/0/0.u16",
        headers={"Accept-Encoding": "identity"},
    )

    assert response.status_code == 503
    assert response.headers["X-Terrain-Data-Status"] == "build-miss"
    assert "immutable" not in response.headers["Cache-Control"].lower()


def test_tile_outside_manifest_coverage_is_short_cache_404(client):
    tile_x, tile_y, _, _ = lonlat_to_tile_pixel(lon=-74.0, lat=40.7, zoom=12)

    response = client.get(
        f"/api/v2/terrain/hand/hand-test/12/{tile_x}/{tile_y}.u16",
        headers={"Accept-Encoding": "identity"},
    )

    assert response.status_code == 404
    assert response.headers["X-Terrain-Data-Status"] == "build-miss"
    assert "immutable" not in response.headers["Cache-Control"].lower()


def test_batch_rejects_tiles_outside_manifest_coverage(client):
    tile_x, tile_y, _, _ = lonlat_to_tile_pixel(lon=-74.0, lat=40.7, zoom=12)

    response = client.post(
        "/api/v2/terrain/hand/hand-test/batch.u16",
        headers={"Accept-Encoding": "identity"},
        json={"tiles": [{"z": 12, "x": tile_x, "y": tile_y}]},
    )

    assert response.status_code == 404
    assert response.headers["X-Terrain-Data-Status"] == "build-miss"


def test_bad_xyz_returns_422_not_internal_error(client):
    response = client.get(
        "/api/v2/terrain/hand/hand-test/0/1/0.u16",
        headers={"Accept-Encoding": "identity"},
    )

    assert response.status_code == 422


def test_renderer_runtime_error_returns_503(client, monkeypatch):
    def fail_render(*_args, **_kwargs):
        raise RuntimeError("rasterio unavailable")

    monkeypatch.setattr(terrain_v2, "render_cog_tile_with_cache", fail_render)

    response = client.get(
        "/api/v2/terrain/hand/hand-test/0/0/0.u16",
        headers={"Accept-Encoding": "identity"},
    )

    assert response.status_code == 503
    assert response.headers["X-Terrain-Data-Status"] == "build-miss"
    assert response.json()["detail"] == "rasterio unavailable"


def test_blocking_renderer_routes_are_sync_for_fastapi_threadpool():
    assert not inspect.iscoroutinefunction(terrain_v2.get_terrain_tile)
    assert not inspect.iscoroutinefunction(terrain_v2.get_terrain_tile_batch)
    assert not inspect.iscoroutinefunction(terrain_v2.sample_terrain)
