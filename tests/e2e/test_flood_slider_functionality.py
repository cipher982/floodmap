"""
Browser coverage for current flood-slider behavior.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from conftest import MapPage


@pytest.mark.asyncio
async def test_default_water_mode_uses_hand_tile_source(map_page: MapPage):
    await map_page.goto_homepage()
    await map_page.wait_for_app_ready()

    assert await map_page.page.locator("#view-mode").count() == 0
    hand_source = await map_page.get_current_tile_source()
    assert "client://hand/" in hand_source


@pytest.mark.asyncio
async def test_water_level_slider_updates_display_and_permalink(map_page: MapPage):
    await map_page.goto_homepage()
    await map_page.wait_for_app_ready()

    await map_page.set_water_level_slider(44)

    state = await map_page.get_map_state()
    display = await map_page.get_water_level_display()
    query = parse_qs(urlparse(map_page.page.url).query)

    assert state["view"] == "hand"
    assert abs(state["water"] - 5.8) < 0.01
    assert display == "Neighborhood"
    assert query["view"] == ["hand"]
    assert query["water"] == ["5.8"]
    assert "lat" in query
    assert "lng" in query
    assert "zoom" in query
