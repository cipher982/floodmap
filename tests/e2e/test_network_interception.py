"""
Network interception tests for debugging tile loading issues.
Automatically captures and analyzes all HTTP requests/responses.
"""

import asyncio

import pytest
from playwright.async_api import Request, Response


@pytest.mark.e2e
class TestNetworkInterception:
    """Automated network debugging for MapLibre tile requests."""

    async def test_comprehensive_network_analysis(self, page):
        """Comprehensive analysis of all network activity during map loading."""

        # Data collection
        all_requests = []
        all_responses = []
        network_timeline = []

        # Network handlers
        def log_request(request: Request):
            timestamp = asyncio.get_event_loop().time()
            req_data = {
                "timestamp": timestamp,
                "type": "request",
                "method": request.method,
                "url": request.url,
                "resource_type": request.resource_type,
                "headers": dict(request.headers),
            }
            all_requests.append(req_data)
            network_timeline.append(req_data)

        def log_response(response: Response):
            timestamp = asyncio.get_event_loop().time()
            resp_data = {
                "timestamp": timestamp,
                "type": "response",
                "url": response.url,
                "status": response.status,
                "ok": response.ok,
                "headers": dict(response.headers),
            }
            all_responses.append(resp_data)
            network_timeline.append(resp_data)

        # Set up monitoring
        page.on("request", log_request)
        page.on("response", log_response)

        print("🕷️ Starting comprehensive network monitoring...")

        # Load the page
        start_time = asyncio.get_event_loop().time()
        await page.goto("http://localhost:8001/")

        # Wait for initial load
        await page.wait_for_selector("#map", timeout=15000)

        # Wait for tiles to load
        await asyncio.sleep(5)

        end_time = asyncio.get_event_loop().time()
        total_time = end_time - start_time

        # Analysis
        print("\n📊 NETWORK ANALYSIS RESULTS:")
        print(f"Total time: {total_time:.2f}s")
        print(f"Total requests: {len(all_requests)}")
        print(f"Total responses: {len(all_responses)}")

        # Categorize requests
        html_requests = [r for r in all_requests if r["resource_type"] == "document"]
        js_requests = [r for r in all_requests if r["resource_type"] == "script"]
        css_requests = [r for r in all_requests if r["resource_type"] == "stylesheet"]
        tile_requests = [
            r
            for r in all_requests
            if any(
                pattern in r["url"]
                for pattern in ["/tiles/", "/vector_tiles/", "/flood_tiles/"]
            )
        ]
        other_requests = [
            r
            for r in all_requests
            if r not in html_requests + js_requests + css_requests + tile_requests
        ]

        print("\n📂 REQUEST BREAKDOWN:")
        print(f"HTML/Document: {len(html_requests)}")
        print(f"JavaScript: {len(js_requests)}")
        print(f"CSS: {len(css_requests)}")
        print(f"Tiles: {len(tile_requests)}")
        print(f"Other: {len(other_requests)}")

        # Analyze tile requests specifically
        if tile_requests:
            print("\n🗺️ TILE REQUEST ANALYSIS:")

            # Group by type
            elevation_tiles = [
                r
                for r in tile_requests
                if "/tiles/" in r["url"]
                and "/vector_tiles/" not in r["url"]
                and "/flood_tiles/" not in r["url"]
            ]
            vector_tiles = [r for r in tile_requests if "/vector_tiles/" in r["url"]]
            flood_tiles = [r for r in tile_requests if "/flood_tiles/" in r["url"]]

            print(f"Elevation tiles: {len(elevation_tiles)}")
            print(f"Vector tiles: {len(vector_tiles)}")
            print(f"Flood tiles: {len(flood_tiles)}")

            # Check for /null/ URLs
            null_tile_requests = [r for r in tile_requests if "/null/" in r["url"]]
            if null_tile_requests:
                print(f"\n❌ FOUND {len(null_tile_requests)} /null/ TILE REQUESTS:")
                for req in null_tile_requests[:10]:
                    print(f"  - {req['url']}")

                # Extract coordinate patterns from /null/ URLs
                import re

                for req in null_tile_requests[:5]:
                    match = re.search(r"/null/[^/]+/(\d+)/(\d+)/(\d+)", req["url"])
                    if match:
                        z, x, y = match.groups()
                        print(f"    Coordinates: z={z}, x={x}, y={y}")
            else:
                print("✅ No /null/ URLs found in tile requests")

        # Response analysis
        failed_responses = [r for r in all_responses if not r["ok"]]
        if failed_responses:
            print(f"\n❌ FAILED RESPONSES ({len(failed_responses)}):")

            # Group by status code
            status_groups = {}
            for resp in failed_responses:
                status = resp["status"]
                if status not in status_groups:
                    status_groups[status] = []
                status_groups[status].append(resp)

            for status, responses in status_groups.items():
                print(f"  {status}: {len(responses)} requests")
                if len(responses) <= 3:
                    for resp in responses:
                        print(f"    - {resp['url']}")

        # Timeline analysis
        print("\n⏰ REQUEST TIMELINE (first 10 requests):")
        for i, event in enumerate(network_timeline[:10]):
            rel_time = event["timestamp"] - start_time
            if event["type"] == "request":
                print(f"  {rel_time:.2f}s: REQ {event['method']} {event['url']}")
            else:
                print(f"  {rel_time:.2f}s: RESP {event['status']} {event['url']}")

        # Assert no /null/ URLs
        null_requests = [r for r in all_requests if "/null/" in r["url"]]
        assert len(null_requests) == 0, (
            f"Found {len(null_requests)} requests with /null/ URLs"
        )

    async def test_tile_url_generation_source(self, page):
        """Debug where the /null/ URLs are being generated."""

        print("🔍 Debugging tile URL generation source...")

        # Capture console logs and errors
        console_logs = []

        def handle_console(msg):
            console_logs.append(
                {
                    "type": msg.type,
                    "text": msg.text,
                    "location": str(msg.location) if msg.location else None,
                }
            )

        page.on("console", handle_console)

        # Navigate and wait
        await page.goto("http://localhost:8001/")
        await page.wait_for_selector("#map")

        # Inject debugging JavaScript
        await page.evaluate("""
            // Override URL construction to log where /null/ comes from
            const originalJoin = URL.prototype.toString;
            URL.prototype.toString = function() {
                const result = originalJoin.call(this);
                if (result.includes('/null/')) {
                    console.error('NULL_URL_GENERATED:', result);
                    console.trace('Stack trace for null URL');
                }
                return result;
            };

            // Log window.location.origin
            console.log('window.location.origin:', window.location.origin);

            // Monitor fetch requests
            const originalFetch = window.fetch;
            window.fetch = function(url, options) {
                console.log('FETCH_REQUEST:', url);
                if (url.includes('/null/')) {
                    console.error('FETCH_NULL_URL:', url);
                    console.trace('Stack trace for null fetch');
                }
                return originalFetch.call(this, url, options);
            };
        """)

        # Wait for map initialization and tile requests
        await asyncio.sleep(5)

        # Analyze console logs
        print("\n📝 CONSOLE LOG ANALYSIS:")
        print(f"Total console messages: {len(console_logs)}")

        error_logs = [log for log in console_logs if log["type"] == "error"]
        warning_logs = [log for log in console_logs if log["type"] == "warning"]
        info_logs = [log for log in console_logs if log["type"] == "log"]

        print(f"Errors: {len(error_logs)}")
        print(f"Warnings: {len(warning_logs)}")
        print(f"Info logs: {len(info_logs)}")

        # Look for URL generation logs
        url_logs = [
            log
            for log in console_logs
            if "window.location.origin" in log["text"]
            or "FETCH_REQUEST" in log["text"]
            or "NULL_URL" in log["text"]
        ]

        if url_logs:
            print("\n🔍 URL GENERATION LOGS:")
            for log in url_logs:
                print(f"  [{log['type']}] {log['text']}")

        # Look for null URL generation
        null_logs = [log for log in console_logs if "null" in log["text"].lower()]
        if null_logs:
            print("\n❌ NULL-RELATED LOGS:")
            for log in null_logs:
                print(f"  [{log['type']}] {log['text']}")

        return console_logs


# Standalone runner for immediate debugging
if __name__ == "__main__":
    import os
    import sys

    from playwright.async_api import async_playwright

    # Add project root to path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

    async def run_network_debug():
        """Run network debugging tests directly."""
        print("🕸️ Running network interception debugging...")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False
            )  # Show browser for debugging
            context = await browser.new_context()
            page = await context.new_page()

            try:
                test_instance = TestNetworkInterception()

                print("\n1️⃣ Comprehensive network analysis...")
                await test_instance.test_comprehensive_network_analysis(page)

                print("\n2️⃣ URL generation source debugging...")
                await test_instance.test_tile_url_generation_source(page)

                print("\n✅ Network debugging completed!")

            except Exception as e:
                print(f"❌ Network debugging failed: {e}")
                import traceback

                traceback.print_exc()
            finally:
                await context.close()
                await browser.close()

    asyncio.run(run_network_debug())
