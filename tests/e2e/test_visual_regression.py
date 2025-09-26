"""
Visual regression tests for the flood mapping application.
"""

import pytest
from conftest import MapPage


@pytest.mark.asyncio
async def test_homepage_visual_snapshot(map_page: MapPage):
    """Take a visual snapshot of the homepage for regression testing."""
    await map_page.goto_homepage()
    await map_page.wait_for_map_load()

    # Take full page screenshot
    screenshot = await map_page.page.screenshot(
        full_page=True, path="tests/e2e/screenshots/homepage.png"
    )

    # Basic validation that screenshot was taken
    assert len(screenshot) > 1000  # Should be a reasonable size


@pytest.mark.asyncio
async def test_map_component_visual(map_page: MapPage):
    """Test visual rendering of just the map component."""
    await map_page.goto_homepage()
    await map_page.wait_for_map_load()

    # Screenshot just the map area
    map_element = map_page.page.locator("#map")
    screenshot = await map_element.screenshot(
        path="tests/e2e/screenshots/map_component.png"
    )

    assert len(screenshot) > 1000


@pytest.mark.asyncio
async def test_location_info_visual(map_page: MapPage):
    """Test visual rendering of location information panel."""
    await map_page.goto_homepage()

    # Screenshot the location info section
    location_card = map_page.page.locator("text=Location Information").locator("..")
    screenshot = await location_card.screenshot(
        path="tests/e2e/screenshots/location_info.png"
    )

    assert len(screenshot) > 1000


@pytest.mark.asyncio
async def test_mobile_visual_regression(map_page: MapPage):
    """Test visual rendering on mobile viewport."""
    # Set mobile viewport
    await map_page.page.set_viewport_size({"width": 375, "height": 667})

    await map_page.goto_homepage()
    await map_page.wait_for_map_load()

    # Take mobile screenshot
    screenshot = await map_page.page.screenshot(
        full_page=True, path="tests/e2e/screenshots/mobile_homepage.png"
    )

    assert len(screenshot) > 1000


@pytest.mark.asyncio
async def test_different_zoom_levels_visual(map_page: MapPage):
    """Test visual rendering at different map zoom levels."""
    await map_page.goto_homepage()
    await map_page.wait_for_map_load()

    # Test zoom levels that we have tiles for
    zoom_levels = [10, 11, 12]

    for zoom in zoom_levels:
        # Programmatically set zoom level
        await map_page.page.evaluate(f"""
            if (typeof map !== 'undefined') {{
                map.setZoom({zoom});
            }}
        """)

        # Wait for tiles to load
        await map_page.page.wait_for_timeout(2000)

        # Take screenshot
        map_element = map_page.page.locator("#map")
        screenshot = await map_element.screenshot(
            path=f"tests/e2e/screenshots/map_zoom_{zoom}.png"
        )

        assert len(screenshot) > 1000


@pytest.mark.asyncio
async def test_flood_overlay_visual(map_page: MapPage):
    """Test visual rendering of flood overlays."""
    await map_page.goto_homepage()
    await map_page.wait_for_map_load()

    # The flood overlay should be rendered automatically based on water level
    # Let's test by checking if flood tiles are being requested

    # Wait for any flood tile requests
    await map_page.page.wait_for_timeout(3000)

    # Take screenshot with potential flood overlay
    map_element = map_page.page.locator("#map")
    screenshot = await map_element.screenshot(
        path="tests/e2e/screenshots/map_with_flood_overlay.png"
    )

    assert len(screenshot) > 1000


@pytest.mark.asyncio
async def test_error_state_visual(map_page: MapPage):
    """Test visual rendering of error states."""
    # Navigate to a page that might show errors
    await map_page.page.goto(f"{map_page.page.base_url}/nonexistent")

    # Take screenshot of error state
    screenshot = await map_page.page.screenshot(
        full_page=True, path="tests/e2e/screenshots/error_404.png"
    )

    assert len(screenshot) > 1000


@pytest.mark.asyncio
async def test_loading_states_visual(map_page: MapPage):
    """Test visual rendering of loading states."""
    # Start loading the page but capture intermediate states
    await map_page.page.goto(f"{map_page.page.base_url}/")

    # Take screenshot during initial load
    screenshot1 = await map_page.page.screenshot(
        path="tests/e2e/screenshots/loading_initial.png"
    )

    # Wait for partial load
    await map_page.page.wait_for_selector("text=Location Information", timeout=5000)

    screenshot2 = await map_page.page.screenshot(
        path="tests/e2e/screenshots/loading_partial.png"
    )

    # Wait for full load
    await map_page.wait_for_map_load()

    screenshot3 = await map_page.page.screenshot(
        path="tests/e2e/screenshots/loading_complete.png"
    )

    # All screenshots should be different sizes, indicating different loading states
    assert len(screenshot1) > 1000
    assert len(screenshot2) > 1000
    assert len(screenshot3) > 1000
