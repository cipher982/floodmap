#!/usr/bin/env python3
"""
Simple E2E test to verify the setup works.
"""

import asyncio
import subprocess
import time
import requests
from playwright.async_api import async_playwright


async def test_basic_functionality():
    """Basic test to verify server and browser work together."""
    
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
        # Start Playwright
        print("Starting Playwright...")
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()
        
        print("Navigating to homepage...")
        await page.goto("http://localhost:5001/")
        await page.wait_for_load_state("networkidle")
        
        # Check page title
        title = await page.title()
        print(f"Page title: {title}")
        assert "Flood Buddy" in title
        
        # Check for main content
        content = await page.text_content("body")
        assert "Location Information" in content
        assert "Tampa" in content
        
        # Take a screenshot
        await page.screenshot(path="test_screenshot.png")
        print("Screenshot saved as test_screenshot.png")
        
        # Test API endpoint
        response = await page.request.get("http://localhost:5001/risk/10")
        if response.status == 200:
            data = await response.json()
            print(f"Risk API response: {data}")
            assert "latitude" in data
        else:
            print(f"Risk API returned status {response.status}")
        
        # Test tile endpoint
        response = await page.request.get("http://localhost:5001/tiles/10/275/427")
        print(f"Tile endpoint status: {response.status}")
        
        print("✅ All tests passed!")
        
    finally:
        # Cleanup
        if 'browser' in locals():
            await browser.close()
        if 'playwright' in locals():
            await playwright.stop()
        process.terminate()
        process.wait()


if __name__ == "__main__":
    asyncio.run(test_basic_functionality())