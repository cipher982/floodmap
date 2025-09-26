"""
Automated browser tests for MapLibre debugging.
Captures network requests, HTML generation, and JavaScript console errors.
"""

import asyncio
import json
import re

import pytest
from playwright.async_api import Request, Response, async_playwright


@pytest.mark.e2e
class TestMapLibreAutomated:
    """Automated tests to debug MapLibre tile loading issues."""

    async def test_maplibre_network_requests_capture(self, page):
        """Capture and analyze all network requests made by MapLibre."""

        # Lists to capture requests and responses
        requests_made = []
        responses_received = []
        console_messages = []

        # Network request handler
        def handle_request(request: Request):
            requests_made.append(
                {
                    "url": request.url,
                    "method": request.method,
                    "headers": dict(request.headers),
                    "resource_type": request.resource_type,
                }
            )

        # Response handler
        def handle_response(response: Response):
            responses_received.append(
                {
                    "url": response.url,
                    "status": response.status,
                    "headers": dict(response.headers),
                    "ok": response.ok,
                }
            )

        # Console message handler
        def handle_console(msg):
            console_messages.append(
                {"type": msg.type, "text": msg.text, "location": msg.location}
            )

        # Set up handlers
        page.on("request", handle_request)
        page.on("response", handle_response)
        page.on("console", handle_console)

        # Navigate to the homepage
        print("🌐 Loading homepage...")
        await page.goto("http://localhost:8001/")

        # Wait for map to initialize
        print("⏳ Waiting for map initialization...")
        await page.wait_for_selector("#map", timeout=10000)

        # Wait a bit more for tile requests to be made
        await asyncio.sleep(3)

        # Analyze tile requests
        tile_requests = [
            r
            for r in requests_made
            if "/tiles/" in r["url"]
            or "/vector_tiles/" in r["url"]
            or "/flood_tiles/" in r["url"]
        ]

        print("\n📊 ANALYSIS RESULTS:")
        print(f"Total requests: {len(requests_made)}")
        print(f"Tile requests: {len(tile_requests)}")
        print(f"Console messages: {len(console_messages)}")

        # Check for /null/ URLs
        null_requests = [r for r in tile_requests if "/null/" in r["url"]]
        if null_requests:
            print(f"\n❌ FOUND {len(null_requests)} REQUESTS WITH /null/ URLS:")
            for req in null_requests[:5]:  # Show first 5
                print(f"  - {req['url']}")

        # Check tile request patterns
        print("\n🗺️ TILE REQUEST PATTERNS:")
        for req in tile_requests[:10]:  # Show first 10
            print(f"  - {req['method']} {req['url']}")

        # Check responses
        failed_responses = [r for r in responses_received if not r["ok"]]
        if failed_responses:
            print(f"\n❌ FAILED RESPONSES ({len(failed_responses)}):")
            for resp in failed_responses[:5]:  # Show first 5
                print(f"  - {resp['status']} {resp['url']}")

        # Check console errors
        error_messages = [m for m in console_messages if m["type"] == "error"]
        if error_messages:
            print(f"\n🚨 CONSOLE ERRORS ({len(error_messages)}):")
            for msg in error_messages[:5]:  # Show first 5
                print(f"  - {msg['text']}")

        # Assertions for automated testing
        assert len(null_requests) == 0, (
            f"Found {len(null_requests)} requests with /null/ URLs"
        )
        assert len(error_messages) == 0, f"Found {len(error_messages)} console errors"

    async def test_maplibre_html_generation(self, page):
        """Test the actual HTML generated for MapLibre configuration."""

        print("🔍 Analyzing MapLibre HTML generation...")

        # Navigate to homepage
        await page.goto("http://localhost:8001/")
        await page.wait_for_selector("#map")

        # Get the page content
        html_content = await page.content()

        # Extract MapLibre configuration from script tags
        script_pattern = r"new maplibregl\.Map\(\{(.*?)\}\);"
        matches = re.findall(script_pattern, html_content, re.DOTALL)

        if matches:
            config_str = matches[0]
            print("\n📋 MAPLIBRE CONFIG FOUND:")
            print(f"Config length: {len(config_str)} characters")

            # Look for tile URL patterns
            tile_patterns = [
                r"'/tiles/\{z\}/\{x\}/\{y\}'",
                r"'/vector_tiles/\{z\}/\{x\}/\{y\}\.pbf'",
                r"'/flood_tiles/[^']+/\{z\}/\{x\}/\{y\}'",
            ]

            for pattern in tile_patterns:
                if re.search(pattern, config_str):
                    print(f"✅ Found valid pattern: {pattern}")
                else:
                    print(f"❌ Missing pattern: {pattern}")

            # Check for /null/ in config
            if "/null/" in config_str:
                print("❌ FOUND /null/ IN CONFIG!")
                # Find the specific lines with /null/
                lines_with_null = [
                    line.strip() for line in config_str.split("\n") if "/null/" in line
                ]
                for line in lines_with_null:
                    print(f"  - {line}")
            else:
                print("✅ No /null/ found in config")

            # Check tile URL construction
            if "window.location.origin" in config_str:
                print("✅ Using window.location.origin for URLs")
            else:
                print("❌ Not using window.location.origin")

        else:
            print("❌ No MapLibre config found in HTML!")

        # Check for template placeholders
        placeholder_patterns = ["{z}", "{x}", "{y}"]
        for pattern in placeholder_patterns:
            if pattern in html_content:
                print(f"✅ Found placeholder: {pattern}")
            else:
                print(f"❌ Missing placeholder: {pattern}")

        # Assertions
        assert "/null/" not in html_content, "HTML contains /null/ URLs"
        assert len(matches) > 0, "No MapLibre configuration found"

    async def test_javascript_execution_debugging(self, page):
        """Test JavaScript execution and variable evaluation."""

        print("🔧 Testing JavaScript execution...")

        await page.goto("http://localhost:8001/")
        await page.wait_for_selector("#map")

        # Wait for MapLibre to load
        await asyncio.sleep(2)

        try:
            # Check if MapLibre is loaded
            maplibre_loaded = await page.evaluate("typeof maplibregl !== 'undefined'")
            print(f"MapLibre loaded: {maplibre_loaded}")

            # Check if map is initialized
            map_exists = await page.evaluate("typeof map !== 'undefined'")
            print(f"Map object exists: {map_exists}")

            if map_exists:
                # Get map center
                map_center = await page.evaluate("map.getCenter()")
                print(f"Map center: {map_center}")

                # Get map zoom
                map_zoom = await page.evaluate("map.getZoom()")
                print(f"Map zoom: {map_zoom}")

                # Get map style
                map_style = await page.evaluate(
                    "JSON.stringify(map.getStyle().sources)"
                )
                sources = json.loads(map_style)
                print(f"Map sources: {list(sources.keys())}")

                # Check tile URL templates
                for source_name, source_config in sources.items():
                    if "tiles" in source_config:
                        tile_urls = source_config["tiles"]
                        print(f"Source '{source_name}' tiles: {tile_urls}")

                        # Check for /null/ in tile URLs
                        for tile_url in tile_urls:
                            if "/null/" in tile_url:
                                print(f"❌ Found /null/ in {source_name}: {tile_url}")
                            else:
                                print(f"✅ Valid tile URL in {source_name}: {tile_url}")

        except Exception as e:
            print(f"JavaScript evaluation error: {e}")

    async def test_tile_request_debugging(self, page):
        """Debug specific tile requests to understand URL generation."""

        print("🎯 Debugging tile request generation...")

        failed_requests = []
        successful_requests = []

        def handle_response(response: Response):
            if (
                "/tiles/" in response.url
                or "/vector_tiles/" in response.url
                or "/flood_tiles/" in response.url
            ):
                if response.ok:
                    successful_requests.append(response.url)
                else:
                    failed_requests.append(
                        {
                            "url": response.url,
                            "status": response.status,
                            "status_text": response.status_text,
                        }
                    )

        page.on("response", handle_response)

        await page.goto("http://localhost:8001/")
        await page.wait_for_selector("#map")

        # Wait for tile requests
        await asyncio.sleep(5)

        print("\n📈 TILE REQUEST RESULTS:")
        print(f"Successful requests: {len(successful_requests)}")
        print(f"Failed requests: {len(failed_requests)}")

        if successful_requests:
            print("\n✅ SUCCESSFUL TILE REQUESTS:")
            for url in successful_requests[:5]:
                print(f"  - {url}")

        if failed_requests:
            print("\n❌ FAILED TILE REQUESTS:")
            for req in failed_requests[:10]:
                print(f"  - {req['status']} {req['url']}")

        # Check for patterns in failed requests
        null_failures = [r for r in failed_requests if "/null/" in r["url"]]
        if null_failures:
            print(f"\n🚨 NULL URL FAILURES ({len(null_failures)}):")
            for req in null_failures[:5]:
                print(f"  - {req['url']}")


@pytest.fixture
async def page():
    """Playwright page fixture for browser testing."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)  # Set to False to see browser
        context = await browser.new_context()
        page = await context.new_page()

        yield page

        await context.close()
        await browser.close()


# Standalone test runner for quick debugging
if __name__ == "__main__":
    import os
    import sys

    # Add project root to path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

    async def run_debug_tests():
        """Run debug tests directly."""
        print("🚀 Running MapLibre debugging tests...")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)  # Show browser
            context = await browser.new_context()
            page = await context.new_page()

            try:
                test_instance = TestMapLibreAutomated()

                print("\n1️⃣ Testing network requests...")
                await test_instance.test_maplibre_network_requests_capture(page)

                print("\n2️⃣ Testing HTML generation...")
                await test_instance.test_maplibre_html_generation(page)

                print("\n3️⃣ Testing JavaScript execution...")
                await test_instance.test_javascript_execution_debugging(page)

                print("\n4️⃣ Testing tile requests...")
                await test_instance.test_tile_request_debugging(page)

                print("\n✅ All debugging tests completed!")

            except Exception as e:
                print(f"❌ Test failed: {e}")
                import traceback

                traceback.print_exc()
            finally:
                await context.close()
                await browser.close()

    asyncio.run(run_debug_tests())
