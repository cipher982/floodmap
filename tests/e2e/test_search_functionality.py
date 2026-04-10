"""
Deterministic browser coverage for the current location-search flow.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest
from conftest import MapPage


@pytest.mark.asyncio
async def test_location_search_moves_map_and_updates_status(map_page: MapPage):
    async def handle_search(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "query": "Tampa",
                    "results": [
                        {
                            "name": "Tampa",
                            "label": "Tampa, Florida, United States",
                            "latitude": 27.95,
                            "longitude": -82.46,
                            "type": "city",
                            "bounds": None,
                        }
                    ],
                }
            ),
        )

    await map_page.page.route("**/api/places/search*", handle_search)
    await map_page.goto_homepage()
    await map_page.wait_for_app_ready()

    await map_page.page.fill("#location-search", "Tampa")
    await map_page.page.click("#location-search-button")
    await map_page.page.wait_for_function(
        """() => document
            .getElementById('location-search-status')
            ?.textContent
            ?.includes('Showing Tampa')""",
        timeout=10000,
    )
    await map_page.page.wait_for_timeout(1300)

    state = await map_page.get_map_state()
    query = parse_qs(urlparse(map_page.page.url).query)
    risk_text = await map_page.page.text_content("#risk-details")

    assert abs(state["lat"] - 27.95) < 0.02
    assert abs(state["lng"] - (-82.46)) < 0.02
    assert abs(state["zoom"] - 10.5) < 0.2
    assert query["view"] == ["elevation"]
    assert query["water"] == ["1.0"]
    assert "lat" in query
    assert "lng" in query
    assert "zoom" in query
    assert "Click any point on the map" in risk_text
