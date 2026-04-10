from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from conftest import MapPage


@pytest.mark.asyncio
async def test_city_slug_page_uses_route_defaults_without_query_params(
    map_page: MapPage,
):
    await map_page.goto_homepage("/fl/tampa")
    await map_page.wait_for_app_ready()

    title = await map_page.page.title()
    heading = await map_page.page.locator("h1").first.text_content()
    breadcrumb = await map_page.page.locator("[aria-label='Breadcrumb']").text_content()
    related_heading = await map_page.page.locator(
        ".location-link-section h3"
    ).last.text_content()
    state = await map_page.get_map_state()
    parsed = urlparse(map_page.page.url)

    assert "Tampa Flood Map" in title
    assert "Flood map for Tampa, Florida" in heading
    assert "FloodMap USA" in breadcrumb
    assert "Tampa, Florida" in breadcrumb
    assert "Related city flood maps" in related_heading
    assert parsed.path == "/fl/tampa"
    assert parsed.query == ""
    assert state["view"] == "flood"
    assert abs(state["water"] - 3.0) < 0.01
    assert abs(state["lat"] - 27.9449854) < 0.03
    assert abs(state["lng"] - (-82.4583107)) < 0.03
    assert abs(state["zoom"] - 10.4) < 0.2


@pytest.mark.asyncio
async def test_city_slug_page_explicit_query_state_overrides_route_defaults(
    map_page: MapPage,
):
    target_url = (
        map_page.page.base_url
        + "/fl/tampa?lat=25.76168&lng=-80.19179&zoom=10.30&view=flood&water=6.0"
    )
    await map_page.page.goto(target_url)
    await map_page.wait_for_app_ready()

    state = await map_page.get_map_state()
    parsed = parse_qs(urlparse(map_page.page.url).query)

    assert abs(state["lat"] - 25.76168) < 0.03
    assert abs(state["lng"] - (-80.19179)) < 0.03
    assert abs(state["zoom"] - 10.3) < 0.2
    assert state["view"] == "flood"
    assert abs(state["water"] - 6.0) < 0.01
    assert parsed["view"] == ["flood"]
    assert parsed["water"] == ["6.0"]
