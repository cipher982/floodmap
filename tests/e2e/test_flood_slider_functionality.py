"""
Browser coverage for current view-mode and flood-slider behavior.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from conftest import MapPage


@pytest.mark.asyncio
async def test_view_mode_switching_updates_client_tile_source(map_page: MapPage):
    await map_page.goto_homepage()
    await map_page.wait_for_app_ready()

    elevation_source = await map_page.get_current_tile_source()
    assert elevation_source == "client://elevation/{z}/{x}/{y}"

    await map_page.set_view_mode("flood")
    flood_source = await map_page.get_current_tile_source()
    assert "client://flood/" in flood_source

    await map_page.set_view_mode("hand")
    hand_source = await map_page.get_current_tile_source()
    assert "client://hand/" in hand_source

    await map_page.set_view_mode("elevation")
    elevation_source_again = await map_page.get_current_tile_source()
    assert elevation_source_again == "client://elevation/{z}/{x}/{y}"


@pytest.mark.asyncio
async def test_water_level_slider_updates_display_and_permalink(map_page: MapPage):
    await map_page.goto_homepage()
    await map_page.wait_for_app_ready()

    await map_page.set_view_mode("flood")
    await map_page.set_water_level_slider(44)

    state = await map_page.get_map_state()
    display = await map_page.get_water_level_display()
    query = parse_qs(urlparse(map_page.page.url).query)

    assert state["view"] == "flood"
    assert abs(state["water"] - 5.8) < 0.01
    assert display == "5.8m"
    assert query["view"] == ["flood"]
    assert query["water"] == ["5.8"]
    assert "lat" in query
    assert "lng" in query
    assert "zoom" in query
