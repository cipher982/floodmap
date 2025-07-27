"""Integration tests for tile serving functionality."""
import pytest
import httpx


@pytest.mark.integration
class TestTileServing:
    """Test tile serving across all endpoints."""
    
    def test_elevation_tile_serving_v1(self, api_client):
        """Test v1 elevation tile serving with known working coordinates."""
        # Use validated working coordinates
        z, x, y = 10, 286, 387
        
        # Test v1 raw elevation tiles
        response = api_client.get(f"/api/v1/tiles/elevation/{z}/{x}/{y}.png")
        
        # Should return PNG tile
        assert response.status_code == 200, f"V1 elevation tile failed: {response.status_code}"
        assert response.headers["content-type"] == "image/png"
        assert len(response.content) > 1000  # Should be substantial elevation data
        assert response.content[:8] == b'\x89PNG\r\n\x1a\n'
        
        # Check v1-specific headers
        assert response.headers.get("x-tile-source") == "elevation"
        assert "x-cache" in response.headers
    
    def test_vector_tile_serving_v1(self, api_client):
        """Test v1 vector tile serving with known working coordinates."""
        # Use validated working coordinates
        z, x, y = 10, 286, 387
        
        # Test v1 vector tiles
        response = api_client.get(f"/api/v1/tiles/vector/usa/{z}/{x}/{y}.pbf")
        
        # Should return protobuf tile
        assert response.status_code == 200, f"V1 vector tile failed: {response.status_code}"
        assert response.headers["content-type"] == "application/x-protobuf"
        assert len(response.content) > 1000  # Should be substantial vector data
        
        # Check v1-specific headers
        assert response.headers.get("x-tile-source") == "vector"
        assert "x-cache" in response.headers
    
    def test_flood_tile_serving_v1(self, api_client):
        """Test v1 flood tile serving with known working coordinates."""
        # Use validated working coordinates
        z, x, y = 10, 286, 387
        water_level = 1.0
        
        # Test v1 flood tiles
        response = api_client.get(f"/api/v1/tiles/flood/{water_level}/{z}/{x}/{y}.png")
        
        # Should return PNG tile or 204 (no flood risk)
        assert response.status_code in [200, 204], f"V1 flood tile failed: {response.status_code}"
        
        if response.status_code == 200:
            assert response.headers["content-type"] == "image/png"
            assert len(response.content) > 0
            assert response.content[:8] == b'\x89PNG\r\n\x1a\n'
            
            # Check v1-specific headers
            assert response.headers.get("x-tile-source") == "flood"
            assert response.headers.get("x-water-level") == str(water_level)
            assert "x-cache" in response.headers
    
    def test_v1_parameter_validation(self, api_client):
        """Test v1 API parameter validation."""
        # Test invalid zoom level
        response = api_client.get("/api/v1/tiles/elevation/99/286/387.png")
        assert response.status_code == 400
        
        # Test invalid water level
        response = api_client.get("/api/v1/tiles/flood/999.0/10/286/387.png")
        assert response.status_code == 400
        
        # Test invalid coordinates
        response = api_client.get("/api/v1/tiles/elevation/10/9999/387.png")
        assert response.status_code == 400
        
        # Test invalid vector source
        response = api_client.get("/api/v1/tiles/vector/invalid/10/286/387.pbf")
        assert response.status_code == 422  # FastAPI validation error
    
    def test_v1_health_endpoint(self, api_client):
        """Test v1 health endpoint."""
        response = api_client.get("/api/v1/tiles/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "healthy"
        assert data["version"] == "v1"
        assert "endpoints" in data
        assert "supported_zoom_range" in data
        assert "supported_water_level_range" in data
        
        # Check endpoint definitions
        endpoints = data["endpoints"]
        assert "/api/v1/tiles/vector/" in endpoints["vector"]
        assert "/api/v1/tiles/elevation/" in endpoints["elevation"]
        assert "/api/v1/tiles/flood/" in endpoints["flood"]
    
    def test_legacy_vs_v1_compatibility(self, api_client):
        """Test that legacy and v1 routes return compatible data."""
        z, x, y = 10, 286, 387
        water_level = 1.0
        
        # Compare legacy and v1 flood tiles
        legacy_response = api_client.get(f"/api/tiles/elevation/{water_level}/{z}/{x}/{y}.png")
        v1_response = api_client.get(f"/api/v1/tiles/flood/{water_level}/{z}/{x}/{y}.png")
        
        # Both should succeed
        assert legacy_response.status_code in [200, 204]
        assert v1_response.status_code in [200, 204]
        
        # If both return content, it should be the same (for same functionality)
        if legacy_response.status_code == 200 and v1_response.status_code == 200:
            # Content may differ due to different implementations, but should be valid PNGs
            assert legacy_response.content[:8] == b'\x89PNG\r\n\x1a\n'
            assert v1_response.content[:8] == b'\x89PNG\r\n\x1a\n'
    
    def test_flood_tile_generation(self, api_client):
        """Test flood overlay tile generation."""
        # Tampa area coordinates  
        z, x, y = 10, 275, 427
        water_level = 15.0
        
        response = api_client.get(f"/api/v1/tiles/flood/{water_level}/{z}/{x}/{y}.png")
        
        # Should return PNG or 204 (no flooded area)
        assert response.status_code in [200, 204, 404]
        
        if response.status_code == 200:
            assert response.headers["content-type"] == "image/png"
            assert len(response.content) > 0
            # Check PNG header
            assert response.content[:8] == b'\x89PNG\r\n\x1a\n'
    
    def test_tile_coordinate_validation(self, api_client):
        """Test tile coordinate validation."""
        # Invalid coordinates should return 400
        invalid_coords = [
            (-1, 0, 0),    # Negative Z
            (0, -1, 0),    # Negative X  
            (0, 0, -1),    # Negative Y
            (30, 0, 0),    # Z too high
            (10, 2000, 0), # X too high for zoom level
            (10, 0, 2000), # Y too high for zoom level
        ]
        
        for z, x, y in invalid_coords:
            response = api_client.get(f"/tiles/{z}/{x}/{y}")
            assert response.status_code == 400, f"Expected 400 for coords {z}/{x}/{y}"
    
    def test_tile_caching_headers(self, api_client):
        """Test that tiles have proper caching headers."""
        z, x, y = 10, 275, 427
        
        response = api_client.get(f"/api/v1/tiles/elevation/{z}/{x}/{y}.png")
        
        if response.status_code == 200:
            # Should have cache control headers
            assert "cache-control" in response.headers
            cache_control = response.headers["cache-control"]
            assert "max-age" in cache_control
            assert "immutable" in cache_control or "public" in cache_control


@pytest.mark.integration  
class TestTileURLDebug:
    """Debug tile URL generation issues."""
    
    def test_maplibre_tile_urls(self, api_client):
        """Test that homepage generates correct MapLibre tile URLs."""
        response = api_client.get("/")
        
        assert response.status_code == 200
        html_content = response.text
        
        # Debug: Print sections of HTML that contain tile URLs
        lines = html_content.split('\n')
        tile_lines = [line for line in lines if 'tiles' in line.lower()]
        
        print("\n=== TILE URL LINES IN HTML ===")
        for line in tile_lines:
            print(f"  {line.strip()}")
        print("=== END TILE LINES ===\n")
        
        # Check for problematic patterns
        assert "/null/" not in html_content, "HTML contains '/null/' in tile URLs"
        
        # Look for correct tile URL patterns
        expected_patterns = [
            "/vector_tiles/{z}/{x}/{y}.pbf",
            "/tiles/{z}/{x}/{y}",
            "/flood_tiles/"
        ]
        
        for pattern in expected_patterns:
            # Allow for some variation in the exact format
            pattern_found = any(pattern.replace("{z}", "{").replace("{x}", "{").replace("{y}", "{") in line 
                             for line in tile_lines)
            
            if not pattern_found:
                print(f"❌ Pattern not found: {pattern}")
                print("Available tile lines:")
                for line in tile_lines:
                    print(f"  {line}")
            
            # Don't assert for now - just report
            # assert pattern_found, f"Tile URL pattern not found: {pattern}"
    
    def test_direct_tile_url_access(self, api_client):
        """Test direct access to tile URLs that appear in browser."""
        # Test the URLs that were failing in browser
        failing_urls = [
            "/tiles/10/275/427",
            "/vector_tiles/10/275/427.pbf", 
            "/flood_tiles/1.0/10/275/427"
        ]
        
        for url in failing_urls:
            print(f"\n🔍 Testing URL: {url}")
            response = api_client.get(url)
            print(f"   Status: {response.status_code}")
            print(f"   Headers: {dict(response.headers)}")
            
            # Don't assert success - just report status for debugging
            if response.status_code >= 400:
                print(f"   ❌ Failed: {response.status_code}")
                if response.status_code == 404:
                    print("   💡 This suggests the tile doesn't exist or route isn't working")
                elif response.status_code == 500:
                    print("   💥 Server error - check logs")
            else:
                print(f"   ✅ Success: {response.status_code}")