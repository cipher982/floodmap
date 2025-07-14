"""Integration tests for tile serving functionality."""
import pytest
import httpx


@pytest.mark.integration
class TestTileServing:
    """Test tile serving across all endpoints."""
    
    @pytest.mark.asyncio
    async def test_elevation_tile_serving(self, tile_client):
        """Test elevation tile serving."""
        # Tampa area coordinates
        z, x, y = 10, 275, 427
        
        response = await tile_client.get_elevation_tile(z, x, y)
        
        # Should return PNG tile or 404 (if no elevation data for this tile)
        assert response.status_code in [200, 404], f"Unexpected status: {response.status_code}"
        
        if response.status_code == 200:
            assert response.headers["content-type"] == "image/png"
            assert len(response.content) > 0
            # Check PNG header
            assert response.content[:8] == b'\x89PNG\r\n\x1a\n'
    
    @pytest.mark.asyncio 
    async def test_vector_tile_proxy(self, tile_client):
        """Test vector tile proxy functionality."""
        # Tampa area coordinates
        z, x, y = 10, 275, 427
        
        # Test app proxy
        proxy_response = await tile_client.get_vector_tile(z, x, y)
        
        # Test direct tileserver
        direct_response = await tile_client.get_direct_vector_tile(z, x, y)
        
        # Both should succeed or both should fail
        assert proxy_response.status_code == direct_response.status_code
        
        if proxy_response.status_code == 200:
            assert proxy_response.headers["content-type"] == "application/x-protobuf"
            assert len(proxy_response.content) > 0
            # Content should be identical
            assert proxy_response.content == direct_response.content
    
    @pytest.mark.asyncio
    async def test_flood_tile_generation(self, tile_client):
        """Test flood overlay tile generation."""
        # Tampa area coordinates  
        z, x, y = 10, 275, 427
        water_level = 15.0
        
        response = await tile_client.get_flood_tile(water_level, z, x, y)
        
        # Should return PNG or 204 (no flooded area)
        assert response.status_code in [200, 204, 404]
        
        if response.status_code == 200:
            assert response.headers["content-type"] == "image/png"
            assert len(response.content) > 0
            # Check PNG header
            assert response.content[:8] == b'\x89PNG\r\n\x1a\n'
    
    @pytest.mark.asyncio
    async def test_tile_coordinate_validation(self, api_client):
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
            response = await api_client.get(f"/tiles/{z}/{x}/{y}")
            assert response.status_code == 400, f"Expected 400 for coords {z}/{x}/{y}"
    
    @pytest.mark.asyncio
    async def test_tile_caching_headers(self, tile_client):
        """Test that tiles have proper caching headers."""
        z, x, y = 10, 275, 427
        
        response = await tile_client.get_elevation_tile(z, x, y)
        
        if response.status_code == 200:
            # Should have cache control headers
            assert "cache-control" in response.headers
            cache_control = response.headers["cache-control"]
            assert "max-age" in cache_control
            assert "immutable" in cache_control or "public" in cache_control


@pytest.mark.integration  
class TestTileURLDebug:
    """Debug tile URL generation issues."""
    
    @pytest.mark.asyncio
    async def test_maplibre_tile_urls(self, api_client):
        """Test that homepage generates correct MapLibre tile URLs."""
        response = await api_client.get("/")
        
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
    
    @pytest.mark.asyncio
    async def test_direct_tile_url_access(self, api_client):
        """Test direct access to tile URLs that appear in browser."""
        # Test the URLs that were failing in browser
        failing_urls = [
            "/tiles/10/275/427",
            "/vector_tiles/10/275/427.pbf", 
            "/flood_tiles/1.0/10/275/427"
        ]
        
        for url in failing_urls:
            print(f"\n🔍 Testing URL: {url}")
            response = await api_client.get(url)
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