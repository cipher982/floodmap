"""Global test configuration and fixtures."""
import pytest
import asyncio
import os
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import fixtures from sub-modules
try:
    from tests.fixtures.services import (
        service_urls, 
        test_services, 
        api_client, 
        tile_client
    )
except ImportError:
    # Fallback for direct execution
    from fixtures.services import (
        service_urls, 
        test_services, 
        api_client, 
        tile_client
    )


def pytest_configure(config):
    """Configure pytest with custom markers and settings."""
    config.addinivalue_line(
        "markers", "unit: fast unit tests (< 1s each)"
    )
    config.addinivalue_line(
        "markers", "integration: integration tests requiring services (< 10s each)"
    )
    config.addinivalue_line(
        "markers", "e2e: end-to-end browser tests (< 30s each)"
    )
    config.addinivalue_line(
        "markers", "visual: visual regression tests"
    )
    config.addinivalue_line(
        "markers", "performance: performance and load tests"
    )
    config.addinivalue_line(
        "markers", "slow: slow tests that can be skipped in development"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers and skip slow tests in dev mode."""
    
    # Add markers based on test location
    for item in items:
        # Add markers based on file path
        if "unit/" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        elif "integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "e2e/" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)
        elif "visual/" in str(item.fspath):
            item.add_marker(pytest.mark.visual)
        elif "performance/" in str(item.fspath):
            item.add_marker(pytest.mark.performance)
    
    # Skip slow tests in development mode (when -x or --maxfail is used)
    if config.getoption("-x") or config.getoption("--maxfail"):
        skip_slow = pytest.mark.skip(reason="Skipping slow tests in development mode")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def test_data_dir():
    """Path to test data directory."""
    return Path(__file__).parent / "data"


@pytest.fixture  
def mock_tile_data():
    """Generate mock tile data for testing."""
    from PIL import Image
    import io
    
    # Create a simple test tile (256x256 PNG)
    img = Image.new("RGBA", (256, 256), (100, 150, 200, 255))
    
    # Add some pattern to make it recognizable
    for x in range(0, 256, 32):
        for y in range(0, 256, 32):
            for i in range(8):
                for j in range(8):
                    if (x + i) < 256 and (y + j) < 256:
                        img.putpixel((x + i, y + j), (255, 255, 255, 255))
    
    # Convert to bytes
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def mock_elevation_data():
    """Generate mock elevation data for testing."""
    import numpy as np
    
    return {
        "bounds": {
            "north": 28.0, 
            "south": 27.0, 
            "east": -82.0, 
            "west": -83.0
        },
        "data": np.random.randint(0, 50, (100, 100)).astype(np.float32),
        "shape": (100, 100),
        "transform": [0.01, 0.0, -83.0, 0.0, -0.01, 28.0]  # Simple transform
    }


@pytest.fixture
def sample_coordinates():
    """Sample coordinates for testing (Tampa area)."""
    return [
        {"lat": 27.9506, "lon": -82.4585, "name": "Tampa"},
        {"lat": 27.7617, "lon": -82.6404, "name": "St. Petersburg"}, 
        {"lat": 28.0436, "lon": -82.2819, "name": "Brandon"},
    ]


# Environment-specific fixtures
@pytest.fixture
def is_ci():
    """Check if running in CI environment."""
    return os.getenv("CI", "false").lower() == "true"


@pytest.fixture  
def test_mode():
    """Get test mode (unit, integration, e2e, all)."""
    return os.getenv("TEST_MODE", "all")


# Async testing helpers
@pytest.fixture
async def async_client():
    """Async HTTP client for testing."""
    import httpx
    async with httpx.AsyncClient() as client:
        yield client