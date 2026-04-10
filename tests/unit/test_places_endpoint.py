from __future__ import annotations

import httpx
import pytest
from fastapi import HTTPException


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_search_places_parses_results_and_hits_cache(monkeypatch):
    from routers import places

    places._search_cache.clear()
    calls = []

    class FakeClient:
        async def get(self, url, params=None, headers=None):
            calls.append((url, params, headers))
            return FakeResponse(
                [
                    {
                        "display_name": "Tampa, Hillsborough County, Florida, United States",
                        "lat": "27.9449854",
                        "lon": "-82.4583107",
                        "boundingbox": [
                            "27.8126539",
                            "28.1713602",
                            "-82.6488200",
                            "-82.2538678",
                        ],
                        "addresstype": "city",
                        "category": "boundary",
                        "type": "administrative",
                        "address": {"city": "Tampa", "state": "Florida"},
                    }
                ]
            )

    async def fake_get_http_client():
        return FakeClient()

    monkeypatch.setattr(places, "get_http_client", fake_get_http_client)

    first = await places.search_places(q="  Tampa  ", limit=5)
    second = await places.search_places(q="tampa", limit=5)

    assert len(calls) == 1
    assert first.query == "Tampa"
    assert second.results[0].name == "Tampa"
    assert first.results[0].label.startswith("Tampa, Hillsborough County")
    assert first.results[0].bounds is not None
    assert first.results[0].bounds.south == pytest.approx(27.8126539)
    assert calls[0][1]["countrycodes"] == "us"
    assert "FloodMap" in calls[0][2]["User-Agent"]


@pytest.mark.asyncio
async def test_search_places_rejects_short_queries():
    from routers import places

    with pytest.raises(HTTPException) as exc_info:
        await places.search_places(q=" ", limit=5)

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_search_places_maps_provider_failures_to_502(monkeypatch):
    from routers import places

    places._search_cache.clear()

    class FakeClient:
        async def get(self, url, params=None, headers=None):
            raise httpx.ConnectError("boom")

    async def fake_get_http_client():
        return FakeClient()

    monkeypatch.setattr(places, "get_http_client", fake_get_http_client)

    with pytest.raises(HTTPException) as exc_info:
        await places.search_places(q="Miami", limit=5)

    assert exc_info.value.status_code == 502
