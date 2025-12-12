#!/usr/bin/env python3
"""
Complete integration test that starts services, tests them, and shuts down.
Self-contained - doesn't rely on external service management.
"""

import io
import subprocess
import time
from pathlib import Path

import pytest
import requests
from PIL import Image


class ServiceManager:
    def __init__(self):
        self.base_dir = Path("/Users/davidrose/git/floodmap")
        self.api_process = None
        self.tileserver_process = None
        self.processes = []

    def start_services(self):
        """Start both API and TileServer services."""
        # Kill any existing processes on our ports
        try:
            subprocess.run(["pkill", "-f", "uvicorn.*main"], capture_output=True)
            subprocess.run(["docker", "stop", "tileserver-local"], capture_output=True)
            time.sleep(2)
        except:
            pass

        # Update TileServer config
        subprocess.run(
            ["uv", "run", "python", "scripts/update_tileserver_config.py"],
            cwd=self.base_dir,
            check=True,
        )

        # Start TileServer
        tileserver_cmd = [
            "docker",
            "run",
            "--rm",
            "--name",
            "tileserver-local",
            "-p",
            "8080:8080",
            "-v",
            f"{self.base_dir}/map_data:/data",
            "maptiler/tileserver-gl",
            "--config",
            "/data/config.json",
        ]
        self.tileserver_process = subprocess.Popen(
            tileserver_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        self.processes.append(self.tileserver_process)

        # Start API
        api_cmd = [
            "uv",
            "run",
            "uvicorn",
            "main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "5002",
        ]
        self.api_process = subprocess.Popen(
            api_cmd,
            cwd=self.base_dir / "flood-map-v2/api",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.processes.append(self.api_process)

        # Wait for services to be ready
        self._wait_for_services()

    def _wait_for_services(self, timeout=60):
        """Wait for both services to be responsive."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # Check API
                api_response = requests.get(
                    "http://localhost:5002/api/health", timeout=2
                )
                api_ready = api_response.status_code == 200

                # Check TileServer
                tile_response = requests.get("http://localhost:8080", timeout=2)
                tile_ready = tile_response.status_code == 200

                if api_ready and tile_ready:
                    return True

            except requests.RequestException:
                pass

            time.sleep(1)

        # Get error details before failing
        api_output = ""
        tile_output = ""

        if self.api_process:
            try:
                api_stdout, _ = self.api_process.communicate(timeout=1)
                api_output = api_stdout.decode()[:500] if api_stdout else "No output"
            except:
                api_output = "Could not read API output"

        if self.tileserver_process:
            try:
                tile_stdout, _ = self.tileserver_process.communicate(timeout=1)
                tile_output = tile_stdout.decode()[:500] if tile_stdout else "No output"
            except:
                tile_output = "Could not read TileServer output"

        raise Exception(
            f"Services failed to start within timeout. API: {api_output}. TileServer: {tile_output}"
        )

    def stop_services(self):
        """Stop all services."""
        for process in self.processes:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()

        # Stop docker container
        subprocess.run(
            ["docker", "stop", "tileserver-local"], capture_output=True, timeout=10
        )


@pytest.fixture(scope="session")
def services():
    """Start services for the test session."""
    manager = ServiceManager()
    manager.start_services()
    yield manager
    manager.stop_services()


def test_elevation_tile_generation(services):
    """Test that elevation tiles are generated correctly."""
    # Test a Tampa area tile
    response = requests.get(
        "http://localhost:5002/api/tiles/elevation/1/10/277/428.png", timeout=10
    )

    assert response.status_code == 200, f"Elevation tile failed: {response.status_code}"
    assert response.headers.get("content-type") == "image/png"

    # Verify it's a valid PNG image
    image = Image.open(io.BytesIO(response.content))
    assert image.format == "PNG"
    assert image.size == (256, 256)

    # Check that it's not just a solid color (indicates actual data)
    colors = image.getcolors(maxcolors=256 * 256)
    assert len(colors) > 1, "Tile appears to be solid color - no elevation data loaded"


def test_vector_tile_proxy(services):
    """Test vector tile proxy functionality."""
    # This should either work or fail gracefully, not return 503
    response = requests.get(
        "http://localhost:5002/api/tiles/vector/10/277/428.pbf", timeout=10
    )

    # Should be 200 (success), 204 (empty), or 400 (bad request), but NOT 503
    assert response.status_code != 503, f"Vector proxy returning 503: {response.text}"

    if response.status_code == 200:
        assert "protobuf" in response.headers.get("content-type", "")


def test_api_health(services):
    """Test API health endpoint."""
    response = requests.get("http://localhost:5002/api/health", timeout=5)
    assert response.status_code == 200

    health_data = response.json()
    assert health_data.get("status") in ["healthy", "degraded"]


def test_tileserver_availability(services):
    """Test TileServer is available."""
    response = requests.get("http://localhost:8080", timeout=5)
    assert response.status_code == 200


def test_elevation_data_loading_fix(services):
    """Test that the elevation data loading bug is fixed."""
    # This specifically tests the 'shape' vs 'height' metadata fix
    response = requests.get(
        "http://localhost:5002/api/tiles/elevation/1/12/1103/1709.png", timeout=10
    )

    assert response.status_code == 200, "Elevation data loading still broken"

    # Should return actual image, not error
    image = Image.open(io.BytesIO(response.content))
    assert image.format == "PNG"


def test_multiple_water_levels(services):
    """Test different water levels work."""
    water_levels = [0, 1, 3, 10]

    for level in water_levels:
        response = requests.get(
            f"http://localhost:5002/api/tiles/elevation/{level}/10/277/428.png",
            timeout=10,
        )
        assert response.status_code == 200, f"Water level {level} failed"


def test_concurrent_requests(services):
    """Test system handles concurrent requests."""
    import queue
    import threading

    results = queue.Queue()

    def make_request():
        try:
            response = requests.get(
                "http://localhost:5002/api/tiles/elevation/1/10/277/428.png", timeout=10
            )
            results.put(response.status_code == 200)
        except:
            results.put(False)

    # Launch 5 concurrent requests
    threads = []
    for _ in range(5):
        thread = threading.Thread(target=make_request)
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join(timeout=15)

    # Count successes
    successes = 0
    while not results.empty():
        if results.get():
            successes += 1

    assert successes >= 4, f"Only {successes}/5 concurrent requests succeeded"


if __name__ == "__main__":
    # Run with: python tests/test_integration_complete.py
    pytest.main([__file__, "-v", "-s"])
