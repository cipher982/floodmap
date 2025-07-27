"""
Pytest configuration for E2E tests using Playwright.
"""

import pytest
import asyncio
import subprocess
import time
import requests
from typing import Generator
from playwright.async_api import async_playwright, Browser, BrowserContext, Page


# Application configuration
APP_HOST = "localhost"
APP_PORT = 8002  # Use different port for tests
BASE_URL = f"http://{APP_HOST}:{APP_PORT}"


@pytest.fixture(scope="function")
def app_server():
    """Start the application server for testing."""
    import os
    
    # Set environment for test server
    env = os.environ.copy()
    env["API_PORT"] = str(APP_PORT)
    
    # Start the server process
    process = subprocess.Popen(
        ["uv", "run", "python", "main.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd="/Users/davidrose/git/floodmap/src/api",
        env=env
    )
    
    # Wait for server to be ready
    max_retries = 30
    for i in range(max_retries):
        try:
            response = requests.get(f"{BASE_URL}/api/health", timeout=2)
            if response.status_code == 200:
                break
        except requests.exceptions.RequestException:
            time.sleep(1)
        
        # Check if process died
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(f"Server process died: stdout={stdout}, stderr={stderr}")
    else:
        stdout, stderr = process.communicate()
        process.terminate()
        process.wait()
        raise RuntimeError(f"Failed to start application server after {max_retries} tries: stdout={stdout}, stderr={stderr}")
    
    yield BASE_URL
    
    # Cleanup
    process.terminate()
    process.wait()


@pytest.fixture(scope="function")
async def browser():
    """Launch browser for testing."""
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=True,  # Set to False for debugging
        args=["--no-sandbox", "--disable-setuid-sandbox"]
    )
    yield browser
    await browser.close()
    await playwright.stop()


@pytest.fixture
async def context(browser: Browser) -> BrowserContext:
    """Create a new browser context for each test."""
    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
        ignore_https_errors=True
    )
    yield context
    await context.close()


@pytest.fixture
async def page(context: BrowserContext, app_server: str) -> Page:
    """Create a new page for each test."""
    page = await context.new_page()
    
    # Set base URL for convenience
    page.base_url = app_server
    
    yield page
    
    # Ensure all connections are closed
    await page.close()


class MapPage:
    """Page Object Model for the map page."""
    
    def __init__(self, page: Page):
        self.page = page
    
    async def goto_homepage(self):
        """Navigate to the application homepage."""
        await self.page.goto(self.page.base_url + "/")
        await self.page.wait_for_load_state("networkidle")
    
    async def wait_for_map_load(self):
        """Wait for the Google Maps to load."""
        # Wait for the map div to be present
        await self.page.wait_for_selector("#map", timeout=10000)
        
        # Wait for Google Maps API to initialize
        await self.page.wait_for_function(
            "typeof google !== 'undefined' && typeof google.maps !== 'undefined'",
            timeout=15000
        )
        
        # Additional wait for map tiles to load
        await self.page.wait_for_timeout(2000)
    
    async def get_location_info(self):
        """Extract location information from the page."""
        location_info = {}
        
        # Wait for location info to be displayed
        await self.page.wait_for_selector("text=IP Address:", timeout=5000)
        
        # Extract text content
        content = await self.page.text_content("body")
        
        # Parse location information
        lines = content.split("\\n")
        for line in lines:
            if "IP Address:" in line:
                location_info["ip"] = line.split(":")[-1].strip()
            elif "City:" in line:
                location_info["city"] = line.split(":")[-1].strip()
            elif "Latitude:" in line:
                location_info["latitude"] = line.split(":")[-1].strip().replace("°", "")
            elif "Longitude:" in line:
                location_info["longitude"] = line.split(":")[-1].strip().replace("°", "")
            elif "Elevation:" in line:
                location_info["elevation"] = line.split(":")[-1].strip().replace(" m", "")
        
        return location_info
    
    async def check_map_display(self):
        """Check if the map is properly displayed."""
        # Check if map iframe is present and has content
        map_iframe = await self.page.locator("#map").first
        is_visible = await map_iframe.is_visible()
        
        # Check for any error messages
        error_elements = await self.page.locator("text=error").count()
        
        return {
            "map_visible": is_visible,
            "has_errors": error_elements > 0
        }
    
    async def test_elevation_tiles(self):
        """Test if elevation tiles are loading."""
        # Check for tile requests in network
        tile_requests = []
        
        def handle_request(request):
            if "/tiles/" in request.url:
                tile_requests.append(request.url)
        
        self.page.on("request", handle_request)
        
        # Reload page to capture tile requests
        await self.page.reload()
        await self.page.wait_for_load_state("networkidle")
        
        return tile_requests
    
    async def get_flood_risk_data(self, water_level: float = 10.0):
        """Test flood risk endpoint."""
        # Navigate to risk endpoint
        response = await self.page.request.get(f"{self.page.base_url}/risk/{water_level}")
        
        if response.status == 200:
            return await response.json()
        else:
            return {
                "status_code": response.status,
                "error": await response.text()
            }


@pytest.fixture
async def map_page(page: Page) -> MapPage:
    """Create a MapPage instance."""
    return MapPage(page)