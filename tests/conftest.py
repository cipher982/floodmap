"""
Global pytest configuration and fixtures for floodmap tests.
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import requests

# Add API module to path
API_PATH = Path(__file__).parent.parent / "src" / "api"
sys.path.insert(0, str(API_PATH))

# Test configuration
TEST_CONFIG = {
    "api_host": "localhost",
    "api_port": 8000,
    "tileserver_port": 8080,
    "timeout": 30,
    "max_retries": 10,
    "retry_delay": 1,
}

BASE_URL = f"http://{TEST_CONFIG['api_host']}:{TEST_CONFIG['api_port']}"


@pytest.fixture(scope="session")
def test_config() -> dict[str, Any]:
    """Global test configuration."""
    return TEST_CONFIG


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for API requests."""
    return BASE_URL


@pytest.fixture(scope="session")
def api_server():
    """Start API server for testing (session-scoped)."""
    # Check if server is already running
    try:
        response = requests.get(f"{BASE_URL}/api/health", timeout=2)
        if response.status_code == 200:
            yield BASE_URL
            return
    except requests.exceptions.RequestException:
        pass

    # Start server
    env = os.environ.copy()
    env["API_PORT"] = str(TEST_CONFIG["api_port"])

    process = subprocess.Popen(
        ["uv", "run", "python", "main.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(API_PATH),
        env=env,
        text=True,
    )

    # Wait for server to be ready
    for attempt in range(TEST_CONFIG["max_retries"]):
        try:
            response = requests.get(f"{BASE_URL}/api/health", timeout=2)
            if response.status_code == 200:
                break
        except requests.exceptions.RequestException:
            time.sleep(TEST_CONFIG["retry_delay"])
    else:
        process.terminate()
        process.wait()
        raise RuntimeError(
            f"Failed to start API server after {TEST_CONFIG['max_retries']} attempts"
        )

    yield BASE_URL

    # Cleanup
    process.terminate()
    process.wait()


@pytest.fixture
def api_client(base_url):
    """HTTP client for API requests."""
    import requests

    class APIClient:
        def __init__(self, base_url):
            self.base_url = base_url
            self.session = requests.Session()

        def get(self, endpoint, **kwargs):
            return self.session.get(f"{self.base_url}{endpoint}", **kwargs)

        def post(self, endpoint, **kwargs):
            return self.session.post(f"{self.base_url}{endpoint}", **kwargs)

    return APIClient(base_url)


@pytest.fixture
def performance_thresholds():
    """Performance thresholds for different test scenarios."""
    return {
        "fast": 100,  # < 100ms - Excellent
        "acceptable": 500,  # < 500ms - Good
        "slow": 1000,  # < 1s - Acceptable
        "very_slow": 5000,  # < 5s - Poor
        "unacceptable": 10000,  # > 10s - Unacceptable
    }


@pytest.fixture
def sample_tile_coords():
    """Sample tile coordinates for testing."""
    return {
        "tampa": {
            "zoom_10": (10, 277, 429),
            "zoom_11": (11, 555, 858),
            "zoom_12": (12, 1110, 1716),
        },
        "nyc": {
            "zoom_10": (10, 301, 384),
            "zoom_11": (11, 603, 770),
            "zoom_12": (12, 1206, 1540),
        },
        "miami": {
            "zoom_10": (10, 279, 447),
            "zoom_11": (11, 559, 895),
            "zoom_12": (12, 1119, 1791),
        },
    }


@pytest.fixture
def test_water_levels():
    """Standard water levels for testing."""
    return [0.0, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0]


# Markers for different test types
def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line("markers", "unit: fast unit tests (< 1s each)")
    config.addinivalue_line(
        "markers", "integration: integration tests that require running services"
    )
    config.addinivalue_line("markers", "e2e: end-to-end tests using browser automation")
    config.addinivalue_line("markers", "performance: performance and load tests")
    config.addinivalue_line("markers", "visual: visual regression tests")
    config.addinivalue_line(
        "markers", "slow: slow tests that can be skipped in development"
    )
    config.addinivalue_line("markers", "security: security-related tests")


def pytest_collection_modifyitems(config, items):
    """Auto-mark tests based on location."""
    for item in items:
        # Auto-mark tests based on their location
        if "unit/" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        elif "integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "e2e/" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)
        elif "performance/" in str(item.fspath):
            item.add_marker(pytest.mark.performance)
        elif "visual/" in str(item.fspath):
            item.add_marker(pytest.mark.visual)
        elif "security/" in str(item.fspath):
            item.add_marker(pytest.mark.security)

        # Mark slow tests
        if "slow" in item.name.lower() or "stress" in item.name.lower():
            item.add_marker(pytest.mark.slow)


def pytest_runtest_setup(item):
    """Skip tests based on markers and conditions."""
    # Skip slow tests unless explicitly requested
    if "slow" in item.keywords and not item.config.getoption(
        "--runslow", default=False
    ):
        pytest.skip("slow test (use --runslow to run)")


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )
    parser.addoption("--api-url", default=BASE_URL, help="API base URL for testing")
