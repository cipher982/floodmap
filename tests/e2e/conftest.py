"""
Pytest configuration for Playwright-backed end-to-end tests.
"""

from __future__ import annotations

import os
import subprocess
import time

import pytest
import requests
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

APP_HOST = "127.0.0.1"
APP_PORT = 8001
BASE_URL = f"http://{APP_HOST}:{APP_PORT}"


@pytest.fixture(scope="function")
def app_server():
    """Start the local API/web server for browser tests."""
    env = os.environ.copy()
    env["API_PORT"] = str(APP_PORT)
    env["ALLOW_MISSING_DATA"] = "true"
    env["ENVIRONMENT"] = "development"
    env["TERRAIN_V2_ENABLED"] = "true"

    process = subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "main:app",
            "--host",
            APP_HOST,
            "--port",
            str(APP_PORT),
            "--log-level",
            "warning",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd="/Users/davidrose/git/floodmap/src/api",
        env=env,
    )

    max_retries = 30
    for _ in range(max_retries):
        try:
            response = requests.get(f"{BASE_URL}/api/health", timeout=2)
            if response.status_code == 200:
                break
        except requests.exceptions.RequestException:
            time.sleep(1)

        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(
                f"Server process died before becoming healthy: stdout={stdout}, stderr={stderr}"
            )
    else:
        stdout, stderr = process.communicate(timeout=5)
        process.terminate()
        process.wait()
        raise RuntimeError(
            f"Failed to start server after {max_retries} retries: stdout={stdout}, stderr={stderr}"
        )

    yield BASE_URL

    process.terminate()
    process.wait()


@pytest.fixture(scope="function")
async def browser():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-setuid-sandbox"],
    )
    yield browser
    await browser.close()
    await playwright.stop()


@pytest.fixture
async def context(browser: Browser) -> BrowserContext:
    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
        ignore_https_errors=True,
    )
    yield context
    await context.close()


@pytest.fixture
async def page(context: BrowserContext, app_server: str) -> Page:
    page = await context.new_page()
    page.base_url = app_server
    page.max_terrain_request_z = None

    def track_request(req):
        try:
            marker = "/api/v2/terrain/hand/"
            if marker not in req.url:
                return
            rest = req.url.split(marker, 1)[1]
            parts = rest.split("/")
            if len(parts) < 4 or parts[1] == "batch.u16":
                return
            z = int(parts[1])
            if page.max_terrain_request_z is None or z > page.max_terrain_request_z:
                page.max_terrain_request_z = z
        except Exception:
            return

    page.on("request", track_request)

    yield page

    await page.close()


class MapPage:
    def __init__(self, page: Page):
        self.page = page

    async def goto_homepage(self, path: str = "/"):
        await self.page.goto(
            f"{self.page.base_url}{path}", wait_until="domcontentloaded"
        )

    async def wait_for_app_ready(self):
        await self.page.wait_for_selector("#map", state="attached", timeout=10000)
        await self.page.wait_for_function(
            "() => Boolean(window.floodMap && window.floodMap.map)",
            timeout=30000,
        )
        await self.page.wait_for_function(
            "() => window.floodMap.map.loaded()",
            timeout=30000,
        )
        await self.page.wait_for_timeout(400)

    async def get_map_state(self):
        return await self.page.evaluate(
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

    async def set_water_level_slider(self, slider_value: int):
        await self.page.locator("#water-level").evaluate(
            """(slider, value) => {
                slider.value = String(value);
                slider.dispatchEvent(new Event('input', { bubbles: true }));
            }""",
            slider_value,
        )
        await self.page.wait_for_timeout(150)

    async def get_water_level_display(self):
        return await self.page.text_content("#water-level-display")

    async def get_current_tile_source(self):
        return await self.page.evaluate("() => window.floodMap.getTileUrl()")


@pytest.fixture
async def map_page(page: Page) -> MapPage:
    return MapPage(page)
