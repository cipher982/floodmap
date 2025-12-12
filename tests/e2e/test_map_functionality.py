"""
E2E tests for core map functionality.
"""

import pytest
from conftest import MapPage


@pytest.mark.asyncio
async def test_homepage_loads(map_page: MapPage):
    """Test that the homepage loads successfully."""
    await map_page.goto_homepage()

    # Check that the page title is correct
    title = await map_page.page.title()
    assert "FloodMap" in title

    # Check for main heading
    heading = await map_page.page.locator("h1").first.text_content()
    assert "Flood Risk Map" in heading


@pytest.mark.asyncio
async def test_location_info_display(map_page: MapPage):
    """Test that location information is displayed correctly."""
    await map_page.goto_homepage()

    # Location info should render (may be empty until user interacts).
    await map_page.page.wait_for_selector("#location-info", timeout=5000)


@pytest.mark.asyncio
async def test_map_loads_and_displays(map_page: MapPage):
    """Test that the Google Maps component loads and displays."""
    await map_page.goto_homepage()

    # Wait for map to initialize
    await map_page.wait_for_map_load()

    # Check map display status
    map_status = await map_page.check_map_display()

    assert map_status["map_visible"], "Map should be visible"
    assert not map_status["has_errors"], "Map should not have errors"


@pytest.mark.asyncio
async def test_elevation_tiles_loading(map_page: MapPage):
    """Test that elevation tiles are being requested and loaded."""
    await map_page.goto_homepage()
    await map_page.wait_for_map_load()

    # Test elevation tile requests
    tile_requests = await map_page.test_elevation_tiles()

    # Should have some tile requests
    assert len(tile_requests) > 0, "Should have elevation tile requests"

    # Verify tile URLs have correct format
    for tile_url in tile_requests:
        assert "/tiles/" in tile_url
        # Should match pattern /tiles/{z}/{x}/{y}
        parts = tile_url.split("/tiles/")[-1].split("/")
        assert len(parts) == 3, f"Invalid tile URL format: {tile_url}"

        # Verify zoom level is in allowed range (max 11 due to precompressed tile limits)
        zoom = int(parts[0])
        assert zoom <= 11, f"Zoom level {zoom} exceeds max allowed (11)"


@pytest.mark.asyncio
async def test_flood_risk_api(map_page: MapPage):
    """Test the flood risk API endpoint."""
    await map_page.goto_homepage()

    # Test different water levels
    test_levels = [5.0, 10.0, 20.0, 50.0]

    for water_level in test_levels:
        risk_data = await map_page.get_flood_risk_data(water_level)

        # Should return valid risk data (not 404 since we have elevation data)
        assert "latitude" in risk_data, (
            f"Missing latitude for water level {water_level}"
        )
        assert "longitude" in risk_data, (
            f"Missing longitude for water level {water_level}"
        )
        assert "elevation_m" in risk_data, (
            f"Missing elevation for water level {water_level}"
        )
        assert "status" in risk_data, f"Missing status for water level {water_level}"

        # Verify coordinates are Tampa area
        assert 27.0 < risk_data["latitude"] < 29.0
        assert -83.0 < risk_data["longitude"] < -82.0

        # Verify status is either "safe" or "risk"
        assert risk_data["status"] in ["safe", "risk"]


@pytest.mark.asyncio
async def test_flood_tile_generation(map_page: MapPage):
    """Test that flood overlay tiles can be generated."""
    await map_page.goto_homepage()

    # Test flood tile endpoint directly
    water_level = 15.0  # meters

    # Tampa area tile coordinates (zoom 10)
    test_tiles = [(10, 275, 427), (10, 276, 428), (11, 551, 854)]

    for z, x, y in test_tiles:
        response = await map_page.page.request.get(
            f"{map_page.page.base_url}/flood_tiles/{water_level}/{z}/{x}/{y}"
        )

        # Should return either 200 (flood tile) or 204 (no flood in this tile)
        assert response.status in [200, 204], (
            f"Unexpected status {response.status} for tile {z}/{x}/{y}"
        )

        if response.status == 200:
            # Should return PNG image
            content_type = response.headers.get("content-type", "")
            assert "image/png" in content_type, f"Expected PNG, got {content_type}"


@pytest.mark.asyncio
async def test_responsive_design(map_page: MapPage):
    """Test that the application works on different screen sizes."""
    # Test mobile viewport
    await map_page.page.set_viewport_size({"width": 375, "height": 667})
    await map_page.goto_homepage()

    # Check that content is still accessible
    location_info = await map_page.get_location_info()
    assert "city" in location_info

    # Test tablet viewport
    await map_page.page.set_viewport_size({"width": 768, "height": 1024})
    await map_page.goto_homepage()
    await map_page.wait_for_map_load()

    map_status = await map_page.check_map_display()
    assert map_status["map_visible"]

    # Test desktop viewport
    await map_page.page.set_viewport_size({"width": 1920, "height": 1080})
    await map_page.goto_homepage()
    await map_page.wait_for_map_load()

    map_status = await map_page.check_map_display()
    assert map_status["map_visible"]


@pytest.mark.asyncio
async def test_error_handling(map_page: MapPage):
    """Test error handling for invalid requests."""
    await map_page.goto_homepage()

    # Test invalid tile request
    response = await map_page.page.request.get(
        f"{map_page.page.base_url}/tiles/99/999/999"
    )
    assert response.status == 404

    # Test invalid flood tile request
    response = await map_page.page.request.get(
        f"{map_page.page.base_url}/flood_tiles/invalid/10/100/100"
    )
    assert response.status in [400, 422]  # Bad request or validation error

    # Test out of bounds tile request
    response = await map_page.page.request.get(
        f"{map_page.page.base_url}/flood_tiles/10/10/99999/99999"
    )
    assert response.status == 400


@pytest.mark.asyncio
async def test_performance_metrics(map_page: MapPage):
    """Test that the application performance is acceptable."""
    # Measure page load time
    start_time = await map_page.page.evaluate("performance.now()")

    await map_page.goto_homepage()
    await map_page.wait_for_map_load()

    end_time = await map_page.page.evaluate("performance.now()")
    load_time = end_time - start_time

    # Page should load within reasonable time (10 seconds)
    assert load_time < 10000, f"Page load took {load_time}ms, too slow"

    # Check that metrics endpoint is available
    response = await map_page.page.request.get("/metrics")
    assert response.status == 200

    metrics_text = await response.text()
    assert (
        "request_processing_seconds" in metrics_text
        or "Prometheus metrics" in metrics_text
    )


@pytest.mark.asyncio
async def test_max_zoom_matches_precompressed_tiles(map_page: MapPage):
    """Test that map maxZoom is capped to match precompressed tile availability.

    This prevents the bug where zoom levels beyond precompressed tiles
    return NODATA tiles (all water/blue).
    """
    await map_page.goto_homepage()
    await map_page.wait_for_map_load()

    max_zoom = await map_page.page.evaluate("""
        () => {
            if (window.floodMap && window.floodMap.map) {
                return window.floodMap.map.getMaxZoom();
            }
            return null;
        }
    """)

    assert max_zoom is not None, "Could not get map maxZoom"
    assert max_zoom <= 11, (
        f"Map maxZoom ({max_zoom}) exceeds precompressed tile limit (11). "
        "This will cause tiles to appear as water/NODATA at high zoom levels."
    )

    # Regression check: user zoom interactions shouldn't exceed maxZoom.
    # MapLibre's internal zoom is float; allow a tiny epsilon.
    zoom_after = await map_page.page.evaluate("""
        async () => {
            const map = window.floodMap?.map;
            if (!map) return null;

            // Try to exceed max via API and wait for the animation frame.
            map.setZoom(map.getMaxZoom() + 2);
            await new Promise(r => requestAnimationFrame(() => r()));
            return map.getZoom();
        }
    """)
    assert zoom_after is not None, "Could not read map zoom after setZoom"
    assert zoom_after <= (max_zoom + 0.001), (
        f"Map allowed zoom {zoom_after} beyond maxZoom {max_zoom}"
    )
    # Stronger regression check: even when zoom is clamped, MapLibre may request
    # overscaled tiles (z+1). We assert no elevation-data requests exceed z=11.
    # This is validated from Playwright (network layer) in the fixture.
    req_max = getattr(map_page.page, "max_elevation_request_z", None)
    assert req_max is not None, "No elevation tile requests observed"
    assert req_max <= 11, f"Requested elevation tile z={req_max} (>11)"
