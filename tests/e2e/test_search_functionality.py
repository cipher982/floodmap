"""
Deterministic browser coverage for the current location-search flow.
"""

from __future__ import annotations

import asyncio
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


@pytest.mark.asyncio
async def test_location_search_typeahead_shows_suggestions_before_submit(
    map_page: MapPage,
):
    async def handle_search(route):
        query = parse_qs(urlparse(route.request.url).query).get("q", [""])[0]
        if query == "new yo":
            results = [
                {
                    "name": "New York",
                    "label": "New York, New York, United States",
                    "latitude": 40.7128,
                    "longitude": -74.006,
                    "type": "city",
                    "bounds": None,
                },
                {
                    "name": "New York County",
                    "label": "New York County, New York, United States",
                    "latitude": 40.7831,
                    "longitude": -73.9712,
                    "type": "county",
                    "bounds": None,
                },
            ]
        else:
            results = []

        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"query": query, "results": results}),
        )

    await map_page.page.route("**/api/places/search*", handle_search)
    await map_page.goto_homepage()
    await map_page.wait_for_app_ready()

    initial_state = await map_page.get_map_state()

    await map_page.page.fill("#location-search", "new yo")
    await map_page.page.wait_for_function(
        """() => document.querySelectorAll('.search-result').length === 2""",
        timeout=10000,
    )

    status_text = await map_page.page.text_content("#location-search-status")
    suggestion_names = await map_page.page.locator(
        ".search-result__name"
    ).all_text_contents()
    current_path = urlparse(map_page.page.url).path
    state_before_select = await map_page.get_map_state()

    assert status_text.strip() == ""
    assert suggestion_names == ["New York", "New York County"]
    assert current_path == "/"
    assert abs(state_before_select["lat"] - initial_state["lat"]) < 0.001
    assert abs(state_before_select["lng"] - initial_state["lng"]) < 0.001

    await map_page.page.locator(".search-result").first.click()
    await map_page.page.wait_for_function(
        """() => document
            .getElementById('location-search-status')
            ?.textContent
            ?.includes('Showing New York')""",
        timeout=10000,
    )
    await map_page.page.wait_for_timeout(1300)

    state = await map_page.get_map_state()

    assert abs(state["lat"] - 40.7128) < 0.02
    assert abs(state["lng"] - (-74.006)) < 0.02
    assert abs(state["zoom"] - 10.5) < 0.2


@pytest.mark.asyncio
async def test_location_search_typeahead_does_not_shift_share_controls(
    map_page: MapPage,
):
    async def handle_search(route):
        query = parse_qs(urlparse(route.request.url).query).get("q", [""])[0]
        results = []
        if query == "new":
            results = [
                {
                    "name": "New Orleans",
                    "label": "New Orleans Lakefront Airport, Keubel Drive, Seabrook, New Orleans, Orleans Parish, Louisiana, 70126, United States",
                    "latitude": 29.9934,
                    "longitude": -90.258,
                    "type": "city",
                    "bounds": None,
                },
                {
                    "name": "New",
                    "label": "New, Owen County, Kentucky, United States",
                    "latitude": 38.537,
                    "longitude": -84.7922,
                    "type": "hamlet",
                    "bounds": None,
                },
                {
                    "name": "Town of Pound Ridge",
                    "label": "New, Town of Pound Ridge, Westchester County, New York, 10518, United States",
                    "latitude": 41.2085,
                    "longitude": -73.5746,
                    "type": "town",
                    "bounds": None,
                },
            ]

        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"query": query, "results": results}),
        )

    await map_page.page.route("**/api/places/search*", handle_search)
    await map_page.goto_homepage()
    await map_page.wait_for_app_ready()

    share_label = map_page.page.locator("label[for='share-view-button']")
    share_top_before = await share_label.evaluate(
        "(node) => node.getBoundingClientRect().top"
    )

    await map_page.page.fill("#location-search", "new")
    await map_page.page.wait_for_function(
        """() => document.querySelectorAll('.search-result').length === 3""",
        timeout=10000,
    )

    share_top_after = await share_label.evaluate(
        "(node) => node.getBoundingClientRect().top"
    )
    layout_state = await map_page.page.evaluate(
        """() => {
            const shell = document.querySelector('.location-search-shell');
            const results = document.getElementById('location-search-results');
            return {
                resultsPosition: window.getComputedStyle(results).position,
                shellBottom: shell?.getBoundingClientRect().bottom ?? 0,
                resultsTop: results?.getBoundingClientRect().top ?? 0,
            };
        }"""
    )

    assert abs(share_top_after - share_top_before) < 4
    assert layout_state["resultsPosition"] == "absolute"
    assert layout_state["resultsTop"] >= layout_state["shellBottom"] - 1


@pytest.mark.asyncio
async def test_far_location_search_uses_progressive_jump_overlay(map_page: MapPage):
    async def handle_search(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "query": "Seattle",
                    "results": [
                        {
                            "name": "Seattle",
                            "label": "Seattle, Washington, United States",
                            "latitude": 47.6062,
                            "longitude": -122.3321,
                            "type": "city",
                            "bounds": None,
                        }
                    ],
                }
            ),
        )

    async def delay_elevation_tiles(route):
        response = await route.fetch()
        await asyncio.sleep(0.25)
        await route.fulfill(response=response)

    await map_page.page.route("**/api/places/search*", handle_search)
    await map_page.page.route(
        "**/api/v1/tiles/elevation-data/**", delay_elevation_tiles
    )
    await map_page.goto_homepage()
    await map_page.wait_for_app_ready()

    await map_page.page.fill("#location-search", "Seattle")
    await map_page.page.click("#location-search-button")
    await map_page.page.wait_for_function(
        """() => Boolean(window.floodMap.lastProgressiveJumpPlan?.useProgressive)""",
        timeout=10000,
    )
    await map_page.page.wait_for_function(
        """() => document.getElementById('map-transition-overlay')?.dataset?.state === 'active'""",
        timeout=10000,
    )

    overlay_state = await map_page.page.evaluate(
        """() => {
            const overlay = document.getElementById('map-transition-overlay');
            const image = document.getElementById('map-transition-overlay-image');
            return {
                hidden: overlay?.hidden ?? true,
                state: overlay?.dataset?.state ?? '',
                hasImage: Boolean(image?.getAttribute('src'))
            };
        }"""
    )
    plan = await map_page.page.evaluate("() => window.floodMap.lastProgressiveJumpPlan")

    assert overlay_state["hidden"] is False
    assert overlay_state["state"] == "active"
    assert overlay_state["hasImage"] is True
    assert plan["stageZoom"] == 7
    assert plan["distanceKm"] > 3000

    await map_page.page.wait_for_function(
        """() => document.getElementById('map-transition-overlay')?.dataset?.state === 'hidden'""",
        timeout=10000,
    )
    await map_page.page.wait_for_timeout(1100)

    state = await map_page.get_map_state()

    assert abs(state["lat"] - 47.6062) < 0.02
    assert abs(state["lng"] - (-122.3321)) < 0.02
    assert abs(state["zoom"] - 10.5) < 0.2


@pytest.mark.asyncio
async def test_location_search_keyboard_navigation_selects_active_suggestion(
    map_page: MapPage,
):
    async def handle_search(route):
        query = parse_qs(urlparse(route.request.url).query).get("q", [""])[0]
        results = []
        if query == "tampa":
            results = [
                {
                    "name": "Tampa, Florida",
                    "label": "Tampa, Hillsborough County, Florida, United States",
                    "latitude": 27.95,
                    "longitude": -82.46,
                    "type": "city",
                    "bounds": None,
                },
                {
                    "name": "Tampa, Kansas",
                    "label": "Tampa, Marion County, Kansas, 67483, United States",
                    "latitude": 38.5482,
                    "longitude": -97.2417,
                    "type": "hamlet",
                    "bounds": None,
                },
            ]

        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"query": query, "results": results}),
        )

    await map_page.page.route("**/api/places/search*", handle_search)
    await map_page.goto_homepage()
    await map_page.wait_for_app_ready()

    await map_page.page.fill("#location-search", "tampa")
    await map_page.page.wait_for_function(
        """() => document.querySelectorAll('.search-result').length === 2""",
        timeout=10000,
    )

    await map_page.page.press("#location-search", "ArrowDown")
    active_descendant = await map_page.page.locator("#location-search").get_attribute(
        "aria-activedescendant"
    )
    active_name = await map_page.page.locator(
        ".search-result.is-active .search-result__name"
    ).text_content()

    assert active_descendant == "location-search-result-0"
    assert active_name == "Tampa, Florida"

    await map_page.page.press("#location-search", "ArrowDown")
    active_descendant = await map_page.page.locator("#location-search").get_attribute(
        "aria-activedescendant"
    )
    active_name = await map_page.page.locator(
        ".search-result.is-active .search-result__name"
    ).text_content()

    assert active_descendant == "location-search-result-1"
    assert active_name == "Tampa, Kansas"

    await map_page.page.press("#location-search", "ArrowUp")
    active_descendant = await map_page.page.locator("#location-search").get_attribute(
        "aria-activedescendant"
    )
    active_name = await map_page.page.locator(
        ".search-result.is-active .search-result__name"
    ).text_content()

    assert active_descendant == "location-search-result-0"
    assert active_name == "Tampa, Florida"

    await map_page.page.press("#location-search", "ArrowDown")
    await map_page.page.press("#location-search", "Enter")
    await map_page.page.wait_for_function(
        """() => document
            .getElementById('location-search-status')
            ?.textContent
            ?.includes('Showing Tampa, Kansas')""",
        timeout=10000,
    )
    await map_page.page.wait_for_timeout(1300)

    state = await map_page.get_map_state()
    input_value = await map_page.page.input_value("#location-search")
    expanded = await map_page.page.locator("#location-search").get_attribute(
        "aria-expanded"
    )

    assert input_value == "Tampa, Kansas"
    assert expanded == "false"
    assert abs(state["lat"] - 38.5482) < 0.02
    assert abs(state["lng"] - (-97.2417)) < 0.02


@pytest.mark.asyncio
async def test_location_search_escape_dismisses_suggestions(
    map_page: MapPage,
):
    async def handle_search(route):
        query = parse_qs(urlparse(route.request.url).query).get("q", [""])[0]
        results = []
        if query == "tampa":
            results = [
                {
                    "name": "Tampa",
                    "label": "Tampa, Hillsborough County, Florida, United States",
                    "latitude": 27.95,
                    "longitude": -82.46,
                    "type": "city",
                    "bounds": None,
                },
                {
                    "name": "Tampa",
                    "label": "Tampa, Marion County, Kansas, 67483, United States",
                    "latitude": 38.5482,
                    "longitude": -97.2417,
                    "type": "hamlet",
                    "bounds": None,
                },
            ]

        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"query": query, "results": results}),
        )

    await map_page.page.route("**/api/places/search*", handle_search)
    await map_page.goto_homepage()
    await map_page.wait_for_app_ready()

    await map_page.page.fill("#location-search", "tampa")
    await map_page.page.wait_for_function(
        """() => document.querySelectorAll('.search-result').length === 2""",
        timeout=10000,
    )

    await map_page.page.press("#location-search", "ArrowDown")
    await map_page.page.press("#location-search", "Escape")

    await map_page.page.wait_for_function(
        """() => document.querySelectorAll('.search-result').length === 0""",
        timeout=10000,
    )

    expanded = await map_page.page.locator("#location-search").get_attribute(
        "aria-expanded"
    )
    active_descendant = await map_page.page.locator("#location-search").get_attribute(
        "aria-activedescendant"
    )
    status_text = await map_page.page.text_content("#location-search-status")

    assert expanded == "false"
    assert active_descendant is None
    assert status_text.strip() == ""
