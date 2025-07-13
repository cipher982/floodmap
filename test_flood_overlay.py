#!/usr/bin/env python3
"""
Test flood overlay visibility in browser.
"""

import asyncio
import subprocess
import time
import requests
from playwright.async_api import async_playwright


async def test_flood_overlay_display():
    """Test that flood overlays are actually visible in the browser."""
    
    # Start server
    print("Starting server...")
    process = subprocess.Popen(
        ["uv", "run", "python", "run_server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for server to start
    print("Waiting for server to be ready...")
    for i in range(30):
        try:
            response = requests.get("http://localhost:5001/healthz", timeout=2)
            if response.status_code == 200:
                print("Server is ready!")
                break
        except requests.exceptions.RequestException:
            time.sleep(1)
    else:
        process.terminate()
        raise RuntimeError("Server failed to start")
    
    try:
        # Test tile endpoints directly
        print("\n🔍 Testing tile endpoints...")
        
        # Test elevation tiles
        tile_response = requests.get("http://localhost:5001/tiles/10/275/427", timeout=5)
        print(f"Elevation tile (10/275/427): {tile_response.status_code}")
        if tile_response.status_code == 200:
            print(f"✅ Elevation tile working - Size: {len(tile_response.content)} bytes")
        
        # Test flood overlay tiles
        flood_response = requests.get("http://localhost:5001/flood_tiles/10/10/275/427", timeout=5)
        print(f"Flood tile (water_level=10): {flood_response.status_code}")
        if flood_response.status_code == 200:
            print(f"✅ Flood overlay working - Size: {len(flood_response.content)} bytes")
        elif flood_response.status_code == 204:
            print("⚠️  Flood overlay returns 204 (no flood at this level)")
        
        # Test with higher water level
        flood_response_high = requests.get("http://localhost:5001/flood_tiles/50/10/275/427", timeout=5)
        print(f"Flood tile (water_level=50): {flood_response_high.status_code}")
        if flood_response_high.status_code == 200:
            print(f"✅ High flood overlay working - Size: {len(flood_response_high.content)} bytes")
        
        # Start Playwright to check visual display
        print("\n🌐 Testing visual display in browser...")
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=False)  # Show browser for debugging
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()
        
        # Monitor network requests
        tile_requests = []
        flood_requests = []
        
        def handle_request(request):
            if "/tiles/" in request.url:
                tile_requests.append(request.url)
                print(f"📡 Elevation tile request: {request.url}")
            elif "/flood_tiles/" in request.url:
                flood_requests.append(request.url)
                print(f"🌊 Flood tile request: {request.url}")
        
        page.on("request", handle_request)
        
        print("Navigating to homepage...")
        await page.goto("http://localhost:5001/")
        await page.wait_for_load_state("networkidle", timeout=15000)
        
        # Take screenshot
        await page.screenshot(path="flood_test_screenshot.png", full_page=True)
        print("📸 Screenshot saved as flood_test_screenshot.png")
        
        # Check page content
        content = await page.text_content("body")
        if "Tampa" in content:
            print("✅ Location info displayed correctly")
        
        # Wait a bit longer for any delayed tile loading
        print("Waiting for tile requests...")
        await page.wait_for_timeout(5000)
        
        print(f"\n📊 Network Summary:")
        print(f"Elevation tile requests: {len(tile_requests)}")
        print(f"Flood tile requests: {len(flood_requests)}")
        
        if tile_requests:
            print("✅ Elevation tiles being requested")
            # Test one of the tile requests
            sample_tile = tile_requests[0] if tile_requests else None
            if sample_tile:
                tile_url = sample_tile.replace("http://localhost:5001", "")
                tile_test = requests.get(f"http://localhost:5001{tile_url}")
                print(f"Sample tile test: {tile_test.status_code}")
        else:
            print("⚠️  No elevation tile requests detected")
        
        if flood_requests:
            print("✅ Flood overlay tiles being requested") 
        else:
            print("⚠️  No flood overlay requests detected")
        
        # Check if map loaded
        try:
            await page.wait_for_selector("#map", timeout=5000)
            print("✅ Map container found")
            
            # Check for Google Maps initialization
            maps_loaded = await page.evaluate("typeof google !== 'undefined' && typeof google.maps !== 'undefined'")
            if maps_loaded:
                print("✅ Google Maps API loaded")
            else:
                print("⚠️  Google Maps API not loaded (expected - API disabled)")
                
        except Exception as e:
            print(f"❌ Map loading issue: {e}")
        
        # Keep browser open for manual inspection
        print("\n🔍 Browser opened for manual inspection. Check the map for overlays.")
        print("Press Ctrl+C to close and continue...")
        
        try:
            await page.wait_for_timeout(30000)  # Wait 30 seconds for inspection
        except KeyboardInterrupt:
            print("Closing browser...")
        
        await browser.close()
        await playwright.stop()
        
        print("\n✅ Test completed!")
        
    finally:
        # Cleanup
        process.terminate()
        process.wait()


if __name__ == "__main__":
    asyncio.run(test_flood_overlay_display())