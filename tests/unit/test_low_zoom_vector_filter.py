from __future__ import annotations

import gzip
import importlib
import sys

import mapbox_vector_tile
from fastapi import FastAPI
from fastapi.testclient import TestClient


def load_tiles_module(monkeypatch):
    monkeypatch.setenv("ALLOW_MISSING_DATA", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")

    sys.modules.pop("routers.tiles_v1", None)
    return importlib.import_module("routers.tiles_v1")


def build_sample_vector_tile() -> bytes:
    return mapbox_vector_tile.encode(
        [
            {
                "name": "water",
                "features": [
                    {
                        "geometry": "POLYGON ((0 0, 0 32, 32 32, 32 0, 0 0))",
                        "properties": {"class": "lake", "name": "Big Lake"},
                    }
                ],
            },
            {
                "name": "waterway",
                "features": [
                    {
                        "geometry": "LINESTRING (0 0, 32 32)",
                        "properties": {"class": "stream", "name": "Creek"},
                    }
                ],
            },
            {
                "name": "transportation",
                "features": [
                    {
                        "geometry": "LINESTRING (10 0, 10 32)",
                        "properties": {"class": "motorway", "surface": "paved"},
                    }
                ],
            },
            {
                "name": "place",
                "features": [
                    {
                        "geometry": "POINT (20 20)",
                        "properties": {"class": "city", "name": "Tampa"},
                    }
                ],
            },
            {
                "name": "boundary",
                "features": [
                    {
                        "geometry": "LINESTRING (0 10, 32 10)",
                        "properties": {"class": "country"},
                    }
                ],
            },
        ]
    )


def test_filter_low_zoom_vector_tile_content_keeps_only_used_layers(monkeypatch):
    tiles_v1 = load_tiles_module(monkeypatch)
    tiles_v1.filter_low_zoom_vector_tile_content.cache_clear()

    source_tile = build_sample_vector_tile()
    filtered_tile = tiles_v1.filter_low_zoom_vector_tile_content(
        gzip.compress(source_tile)
    )
    decoded = mapbox_vector_tile.decode(filtered_tile)

    assert set(decoded) == {"water", "waterway", "transportation"}
    assert decoded["water"]["features"][0]["properties"] == {"class": "lake"}
    assert decoded["waterway"]["features"][0]["properties"] == {"class": "stream"}
    assert decoded["transportation"]["features"][0]["properties"] == {}
    assert len(filtered_tile) < len(source_tile)


def test_vector_route_filters_only_low_zoom_tiles(monkeypatch):
    tiles_v1 = load_tiles_module(monkeypatch)
    tiles_v1.filter_low_zoom_vector_tile_content.cache_clear()

    sample_tile = build_sample_vector_tile()

    class FakeUpstreamResponse:
        def __init__(self, content: bytes):
            self.status_code = 200
            self.content = content

    class FakeClient:
        def __init__(self, content: bytes):
            self.content = content
            self.calls: list[tuple[str, dict[str, str]]] = []

        async def get(self, url: str, headers: dict[str, str] | None = None):
            self.calls.append((url, headers or {}))
            return FakeUpstreamResponse(self.content)

    fake_client = FakeClient(sample_tile)

    async def fake_get_http_client():
        return fake_client

    monkeypatch.setattr(tiles_v1, "get_http_client", fake_get_http_client)

    app = FastAPI()
    app.include_router(tiles_v1.router)
    client = TestClient(app)

    low_zoom = client.get(
        "/api/v1/tiles/vector/usa/8/1/1.pbf",
        headers={"Accept-Encoding": "identity"},
    )
    high_zoom = client.get(
        "/api/v1/tiles/vector/usa/9/1/1.pbf",
        headers={"Accept-Encoding": "identity"},
    )

    assert low_zoom.status_code == 200
    assert low_zoom.headers["x-vector-profile"] == "low-zoom-filtered"
    assert high_zoom.status_code == 200
    assert "x-vector-profile" not in high_zoom.headers

    low_zoom_decoded = mapbox_vector_tile.decode(low_zoom.content)
    high_zoom_decoded = mapbox_vector_tile.decode(high_zoom.content)

    assert set(low_zoom_decoded) == {"water", "waterway", "transportation"}
    assert "place" in high_zoom_decoded
    assert fake_client.calls[0][1]["Accept-Encoding"] == "identity"
