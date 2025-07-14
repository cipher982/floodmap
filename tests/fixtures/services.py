"""Service management fixtures for testing."""
import pytest
import requests
import time
import subprocess
import os
import signal
from typing import Dict, Optional


@pytest.fixture(scope="session")
def service_urls():
    """URLs for test services."""
    return {
        "app": "http://localhost:5001",
        "tileserver": "http://localhost:8080",
        "redis": "redis://localhost:6379"
    }


@pytest.fixture(scope="session")
def test_services(service_urls):
    """Start and manage test services for the entire test session."""
    services = {}
    
    # Check if services are already running
    app_running = _check_service_health(service_urls["app"] + "/healthz")
    tileserver_running = _check_service_health(service_urls["tileserver"])
    
    if app_running and tileserver_running:
        print("✅ Services already running, using existing instances")
        yield service_urls
        return
    
    print("🚀 Starting test services...")
    
    try:
        # Start tileserver
        if not tileserver_running:
            tileserver_proc = subprocess.Popen(
                ["./start_tileserver.sh"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            services["tileserver"] = tileserver_proc
            
            # Wait for tileserver to be ready
            _wait_for_service(service_urls["tileserver"], timeout=30)
            print("✅ Tileserver ready")
        
        # Start Flask app in test mode
        if not app_running:
            env = os.environ.copy()
            env["DEBUG_MODE"] = "true"
            
            app_proc = subprocess.Popen(
                ["uv", "run", "python", "main.py"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            services["app"] = app_proc
            
            # Wait for app to be ready
            _wait_for_service(service_urls["app"] + "/healthz", timeout=30)
            print("✅ Flask app ready")
        
        yield service_urls
        
    finally:
        # Cleanup services
        print("🧹 Stopping test services...")
        for name, proc in services.items():
            try:
                proc.terminate()
                proc.wait(timeout=5)
                print(f"✅ Stopped {name}")
            except subprocess.TimeoutExpired:
                proc.kill()
                print(f"⚠️  Force killed {name}")
            except Exception as e:
                print(f"❌ Error stopping {name}: {e}")


def _check_service_health(url: str) -> bool:
    """Check if a service is healthy."""
    try:
        response = requests.get(url, timeout=2)
        return response.status_code == 200
    except:
        return False


def _wait_for_service(url: str, timeout: int = 30) -> None:
    """Wait for a service to become available."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                return
        except:
            pass
        time.sleep(1)
    
    raise TimeoutError(f"Service at {url} did not become ready within {timeout}s")


@pytest.fixture
def api_client(service_urls):
    """HTTP client for API testing."""
    import httpx
    
    class APIClient:
        def __init__(self, base_url: str):
            self.base_url = base_url
            self.client = httpx.AsyncClient(base_url=base_url, timeout=30.0)
        
        async def get(self, path: str, **kwargs):
            return await self.client.get(path, **kwargs)
        
        async def post(self, path: str, **kwargs):
            return await self.client.post(path, **kwargs)
        
        async def close(self):
            await self.client.aclose()
    
    client = APIClient(service_urls["app"])
    yield client
    # Cleanup handled by httpx automatically


@pytest.fixture
def tile_client(service_urls):
    """Specialized client for tile testing."""
    import httpx
    
    class TileClient:
        def __init__(self, app_url: str, tileserver_url: str):
            self.app_url = app_url
            self.tileserver_url = tileserver_url
            self.client = httpx.AsyncClient(timeout=30.0)
        
        async def get_elevation_tile(self, z: int, x: int, y: int):
            """Get elevation tile from app."""
            return await self.client.get(f"{self.app_url}/tiles/{z}/{x}/{y}")
        
        async def get_vector_tile(self, z: int, x: int, y: int):
            """Get vector tile from app proxy."""
            return await self.client.get(f"{self.app_url}/vector_tiles/{z}/{x}/{y}.pbf")
        
        async def get_flood_tile(self, water_level: float, z: int, x: int, y: int):
            """Get flood overlay tile."""
            return await self.client.get(f"{self.app_url}/flood_tiles/{water_level}/{z}/{x}/{y}")
        
        async def get_direct_vector_tile(self, z: int, x: int, y: int):
            """Get vector tile directly from tileserver."""
            return await self.client.get(f"{self.tileserver_url}/data/tampa/{z}/{x}/{y}.pbf")
        
        async def close(self):
            await self.client.aclose()
    
    client = TileClient(service_urls["app"], service_urls["tileserver"])
    yield client
    # Will be cleaned up by httpx