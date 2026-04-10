from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest


async def wait_for_map_ready(page):
    await page.goto(page.base_url + "/")
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_function(
        "() => Boolean(window.floodMap && window.floodMap.map)",
        timeout=30000,
    )
    await page.wait_for_function(
        "() => window.floodMap.map.loaded()",
        timeout=30000,
    )


@pytest.mark.asyncio
async def test_permalink_restores_map_state(page):
    target_url = (
        page.base_url + "/?lat=40.71280&lng=-74.00600&zoom=9.50&view=flood&water=6.0"
    )
    await page.goto(target_url)
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_function(
        "() => Boolean(window.floodMap && window.floodMap.map && window.floodMap.map.loaded())",
        timeout=30000,
    )

    state = await page.evaluate(
        """() => {
            const center = window.floodMap.map.getCenter();
            return {
                view: window.floodMap.viewMode,
                water: window.floodMap.currentWaterLevel,
                lat: center.lat,
                lng: center.lng,
                zoom: window.floodMap.map.getZoom()
            };
        }"""
    )

    assert state["view"] == "flood"
    assert abs(state["water"] - 6.0) < 0.01
    assert abs(state["lat"] - 40.7128) < 0.02
    assert abs(state["lng"] - (-74.0060)) < 0.02
    assert abs(state["zoom"] - 9.5) < 0.15


@pytest.mark.asyncio
async def test_permalink_updates_when_map_state_changes(page):
    await wait_for_map_ready(page)

    await page.click("label[for='flood-mode']")
    await page.locator("#water-level").evaluate(
        """(slider) => {
            slider.value = "44";
            slider.dispatchEvent(new Event("input", { bubbles: true }));
        }"""
    )
    await page.evaluate(
        """() => {
            window.floodMap.map.jumpTo({
                center: [-73.98513, 40.75890],
                zoom: 9.25
            });
        }"""
    )
    await page.wait_for_timeout(300)

    parsed = urlparse(page.url)
    query = parse_qs(parsed.query)

    assert query["view"] == ["flood"]
    assert query["water"] == ["5.8"]
    assert abs(float(query["lat"][0]) - 40.7589) < 0.02
    assert abs(float(query["lng"][0]) - (-73.98513)) < 0.02
    assert abs(float(query["zoom"][0]) - 9.25) < 0.15
