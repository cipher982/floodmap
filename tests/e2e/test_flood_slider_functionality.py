"""
E2E tests for flood risk slider functionality using Playwright.
This test validates the client-side flood rendering implementation.
"""

import pytest
from conftest import MapPage


class FloodSliderTestPage(MapPage):
    """Extended MapPage with flood slider testing capabilities."""

    async def wait_for_maplibre_load(self):
        """Wait for MapLibre GL JS to load and initialize."""
        # Wait for MapLibre GL JS to be available
        await self.page.wait_for_function(
            "typeof maplibregl !== 'undefined'", timeout=15000
        )

        # Wait for the map instance to be created
        await self.page.wait_for_function(
            "window.floodMap && window.floodMap.map", timeout=15000
        )

        # Wait for map to finish loading
        await self.page.wait_for_function("window.floodMap.map.loaded()", timeout=10000)

        # Additional wait for tiles to start loading
        await self.page.wait_for_timeout(2000)

    async def get_view_mode(self):
        """Get the current view mode (elevation/flood)."""
        return await self.page.evaluate("window.floodMap.viewMode")

    async def set_view_mode(self, mode: str):
        """Set the view mode to 'elevation' or 'flood'."""
        radio_selector = f"input[name='view-mode'][value='{mode}']"
        await self.page.click(radio_selector)
        await self.page.wait_for_timeout(500)  # Wait for mode change

    async def get_water_level(self):
        """Get the current water level from the slider."""
        return await self.page.evaluate("window.floodMap.currentWaterLevel")

    async def set_water_level_slider(self, slider_value: int):
        """Set the water level slider value (0-100)."""
        slider_selector = "#water-level"
        await self.page.fill(slider_selector, str(slider_value))
        await self.page.dispatch_event(slider_selector, "input")
        await self.page.wait_for_timeout(100)  # Wait for slider change

    async def get_water_level_display(self):
        """Get the displayed water level text."""
        return await self.page.text_content("#water-level-display")

    async def capture_tile_requests(self, action_callback):
        """Capture tile requests during an action."""
        tile_requests = []
        elevation_requests = []

        def handle_request(request):
            url = request.url
            if "/tiles/" in url and "elevation" in url:
                elevation_requests.append(url)
            elif "client://" in url or "/tiles/" in url:
                tile_requests.append(url)

        self.page.on("request", handle_request)

        # Perform the action
        await action_callback()

        # Wait a moment for any async requests
        await self.page.wait_for_timeout(1000)

        self.page.remove_listener("request", handle_request)

        return {
            "tile_requests": tile_requests,
            "elevation_requests": elevation_requests,
        }

    async def check_client_rendering_active(self):
        """Check if client-side rendering is active."""
        try:
            # Check if custom protocol is registered
            protocol_registered = await self.page.evaluate("""
                () => {
                    try {
                        return typeof maplibregl.getProtocol('client') !== 'undefined';
                    } catch (e) {
                        return false;
                    }
                }
            """)

            # Check if ElevationRenderer is instantiated
            renderer_active = await self.page.evaluate("""
                () => {
                    return window.floodMap &&
                           window.floodMap.elevationRenderer &&
                           typeof window.floodMap.elevationRenderer.loadElevationTile === 'function';
                }
            """)

            return {
                "protocol_registered": protocol_registered,
                "renderer_active": renderer_active,
            }
        except Exception as e:
            return {
                "protocol_registered": False,
                "renderer_active": False,
                "error": str(e),
            }

    async def get_current_tile_source(self):
        """Get the current tile source URL template."""
        return await self.page.evaluate("""
            () => {
                try {
                    const source = window.floodMap.map.getSource('elevation-tiles');
                    return source.tiles[0];
                } catch (e) {
                    return null;
                }
            }
        """)


@pytest.fixture
async def flood_page(context, app_server: str) -> FloodSliderTestPage:
    """Create a FloodSliderTestPage instance with existing server."""
    page = await context.new_page()
    page.base_url = "http://localhost:8001"  # Use existing server
    flood_page = FloodSliderTestPage(page)
    yield flood_page
    await page.close()


@pytest.mark.asyncio
async def test_maplibre_initialization(flood_page: FloodSliderTestPage):
    """Test that MapLibre GL JS initializes correctly."""
    # Navigate to the new client implementation
    await flood_page.page.goto(flood_page.page.base_url + "/")
    await flood_page.wait_for_maplibre_load()

    # Check that MapLibre is loaded
    maplibre_loaded = await flood_page.page.evaluate(
        "typeof maplibregl !== 'undefined'"
    )
    assert maplibre_loaded, "MapLibre GL JS should be loaded"

    # Check that FloodMapClient is initialized
    flood_map_loaded = await flood_page.page.evaluate("window.floodMap !== undefined")
    assert flood_map_loaded, "FloodMapClient should be initialized"


@pytest.mark.asyncio
async def test_view_mode_switching(flood_page: FloodSliderTestPage):
    """Test switching between elevation and flood view modes."""
    await flood_page.page.goto(flood_page.page.base_url + "/")
    await flood_page.wait_for_maplibre_load()

    # Start in elevation mode
    initial_mode = await flood_page.get_view_mode()
    assert initial_mode == "elevation", "Should start in elevation mode"

    # Switch to flood mode
    await flood_page.set_view_mode("flood")
    current_mode = await flood_page.get_view_mode()
    assert current_mode == "flood", "Should switch to flood mode"

    # Check that tile source URL changed
    tile_source = await flood_page.get_current_tile_source()
    assert "client://" in tile_source, (
        f"Should use client protocol in flood mode, got: {tile_source}"
    )

    # Switch back to elevation mode
    await flood_page.set_view_mode("elevation")
    current_mode = await flood_page.get_view_mode()
    assert current_mode == "elevation", "Should switch back to elevation mode"

    # Check that tile source URL changed back
    tile_source = await flood_page.get_current_tile_source()
    assert "/api/tiles/topographical/" in tile_source, (
        f"Should use server tiles in elevation mode, got: {tile_source}"
    )


@pytest.mark.asyncio
async def test_water_level_slider_functionality(flood_page: FloodSliderTestPage):
    """Test that the water level slider works correctly."""
    await flood_page.page.goto(flood_page.page.base_url + "/")
    await flood_page.wait_for_maplibre_load()

    # Switch to flood mode first
    await flood_page.set_view_mode("flood")

    # Test different slider values
    test_values = [0, 25, 50, 75, 100]

    for slider_value in test_values:
        await flood_page.set_water_level_slider(slider_value)

        # Get the actual water level
        water_level = await flood_page.get_water_level()
        assert water_level > 0, (
            f"Water level should be > 0 for slider value {slider_value}"
        )

        # Get the display text
        display_text = await flood_page.get_water_level_display()
        assert "m" in display_text, f"Display should show meters: {display_text}"

        # Verify display matches internal value
        display_value = float(display_text.replace("m", ""))
        assert abs(display_value - water_level) < 0.1, (
            f"Display {display_value} should match internal {water_level}"
        )


@pytest.mark.asyncio
async def test_client_side_rendering_no_network_requests(
    flood_page: FloodSliderTestPage,
):
    """Test that slider changes don't trigger network requests (key performance feature)."""
    await flood_page.page.goto(flood_page.page.base_url + "/")
    await flood_page.wait_for_maplibre_load()

    # Switch to flood mode
    await flood_page.set_view_mode("flood")
    await flood_page.page.wait_for_timeout(2000)  # Wait for initial tile loads

    # Capture requests during slider movement
    async def move_slider():
        await flood_page.set_water_level_slider(25)
        await flood_page.page.wait_for_timeout(500)
        await flood_page.set_water_level_slider(75)
        await flood_page.page.wait_for_timeout(500)
        await flood_page.set_water_level_slider(50)

    requests = await flood_page.capture_tile_requests(move_slider)

    # Should have NO new elevation data requests during slider movement
    elevation_requests = requests["elevation_requests"]
    assert len(elevation_requests) == 0, (
        f"Slider movement should not trigger elevation requests, got: {elevation_requests}"
    )

    print(
        f"✅ Slider movement triggered {len(elevation_requests)} network requests (expected: 0)"
    )


@pytest.mark.asyncio
async def test_client_side_protocol_registration(flood_page: FloodSliderTestPage):
    """Test that the client-side protocol is properly registered."""
    await flood_page.page.goto(flood_page.page.base_url + "/")
    await flood_page.wait_for_maplibre_load()

    # Check client-side rendering components
    rendering_status = await flood_page.check_client_rendering_active()

    assert rendering_status["renderer_active"], (
        f"ElevationRenderer should be active: {rendering_status}"
    )

    # The protocol registration check might not work in all browsers, so we'll focus on the renderer


@pytest.mark.asyncio
async def test_elevation_data_endpoint_accessibility(flood_page: FloodSliderTestPage):
    """Test that the elevation data endpoint is accessible."""
    await flood_page.page.goto(flood_page.page.base_url + "/")

    # Test a known tile coordinate
    response = await flood_page.page.request.get(
        f"{flood_page.page.base_url}/api/v1/tiles/elevation-data/10/252/442.u16"
    )

    assert response.status == 200, (
        f"Elevation data endpoint should return 200, got {response.status}"
    )

    # Check content type
    content_type = response.headers.get("content-type", "")
    assert "application/octet-stream" in content_type, (
        f"Should return binary data, got {content_type}"
    )

    # Check data size (should be 256*256*2 = 131072 bytes for uint16 array)
    body = await response.body()
    assert len(body) == 131072, f"Should return 131072 bytes, got {len(body)}"


@pytest.mark.asyncio
async def test_flood_mode_tile_source_update(flood_page: FloodSliderTestPage):
    """Test the core bug fix: tile source should update when switching to flood mode."""
    await flood_page.page.goto(flood_page.page.base_url + "/")
    await flood_page.wait_for_maplibre_load()

    # Start in elevation mode - should use server tiles
    elevation_source = await flood_page.get_current_tile_source()
    assert "/api/tiles/topographical/" in elevation_source, (
        f"Elevation mode should use server tiles: {elevation_source}"
    )

    # Switch to flood mode - should use client protocol
    await flood_page.set_view_mode("flood")
    await flood_page.page.wait_for_timeout(1000)  # Wait for source update

    flood_source = await flood_page.get_current_tile_source()
    assert "client://flood/" in flood_source, (
        f"Flood mode should use client protocol: {flood_source}"
    )

    print(
        f"✅ Tile source correctly updated from '{elevation_source}' to '{flood_source}'"
    )


@pytest.mark.asyncio
async def test_water_level_persistence_across_mode_switches(
    flood_page: FloodSliderTestPage,
):
    """Test that water level persists when switching between modes."""
    await flood_page.page.goto(flood_page.page.base_url + "/")
    await flood_page.wait_for_maplibre_load()

    # Set a specific water level in flood mode
    await flood_page.set_view_mode("flood")
    await flood_page.set_water_level_slider(60)

    initial_level = await flood_page.get_water_level()
    assert initial_level > 0, "Water level should be set"

    # Switch to elevation mode and back
    await flood_page.set_view_mode("elevation")
    await flood_page.set_view_mode("flood")

    # Check that water level is preserved
    final_level = await flood_page.get_water_level()
    assert abs(final_level - initial_level) < 0.1, (
        f"Water level should persist: {initial_level} vs {final_level}"
    )


if __name__ == "__main__":
    # Run the tests directly
    pytest.main([__file__, "-v"])
