"""
Reliable smoke coverage for the current Floodmap app.
"""

from __future__ import annotations

import pytest
from conftest import MapPage


@pytest.mark.asyncio
async def test_homepage_smoke(map_page: MapPage):
    await map_page.goto_homepage()
    await map_page.wait_for_app_ready()

    title = await map_page.page.title()
    heading = await map_page.page.locator("h1").first.text_content()

    assert "FloodMap" in title
    assert "FloodMap USA" in heading
    assert await map_page.page.locator("#map").is_visible()
    assert await map_page.page.locator("#location-search").is_visible()
    assert await map_page.page.locator("#share-view-button").is_visible()

    state = await map_page.get_map_state()
    assert state["view"] == "elevation"
    assert state["zoom"] <= 11


@pytest.mark.asyncio
async def test_health_endpoint_is_available(map_page: MapPage):
    response = await map_page.page.request.get(f"{map_page.page.base_url}/api/health")
    assert response.status == 200

    payload = await response.json()
    assert payload["status"] in {"healthy", "critical"}
    assert payload["deployment_context"]["environment"] == "development"


@pytest.mark.asyncio
async def test_homepage_uses_local_maplibre_assets(map_page: MapPage):
    vendor_requests: list[str] = []
    unpkg_requests: list[str] = []

    def track_request(req):
        if "maplibre-gl" in req.url:
            vendor_requests.append(req.url)
        if "unpkg.com" in req.url:
            unpkg_requests.append(req.url)

    map_page.page.on("request", track_request)

    await map_page.goto_homepage()
    await map_page.wait_for_app_ready()

    assert any("maplibre-gl-4.7.1.css" in url for url in vendor_requests)
    assert any("maplibre-gl-csp-4.7.1.js" in url for url in vendor_requests)
    assert not unpkg_requests


@pytest.mark.asyncio
async def test_max_zoom_matches_precompressed_tile_limit(map_page: MapPage):
    await map_page.goto_homepage()
    await map_page.wait_for_app_ready()

    max_zoom = await map_page.page.evaluate("() => window.floodMap.map.getMaxZoom()")
    assert max_zoom <= 11

    zoom_after = await map_page.page.evaluate(
        """async () => {
            const map = window.floodMap.map;
            map.setZoom(map.getMaxZoom() + 2);
            await new Promise((resolve) => requestAnimationFrame(resolve));
            return map.getZoom();
        }"""
    )
    assert zoom_after <= (max_zoom + 0.001)

    req_max = getattr(map_page.page, "max_elevation_request_z", None)
    assert req_max is not None
    assert req_max <= 11
