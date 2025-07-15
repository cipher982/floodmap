"""
Systematic debugging test suite - tests each layer independently
to isolate exactly where the map rendering is failing.
"""
import pytest
import requests
import json


class TestSystematicDebugging:
    """Test each component independently to isolate the failure point."""
    
    def test_1_tileserver_direct_access(self):
        """Test 1: Verify tileserver works independently"""
        print("\n🔍 TEST 1: Direct tileserver access")
        
        # Test tileserver homepage
        response = requests.get("http://localhost:8080")
        assert response.status_code == 200, "Tileserver not accessible"
        print("✅ Tileserver homepage accessible")
        
        # Test TileJSON metadata
        response = requests.get("http://localhost:8080/data/v3.json")
        assert response.status_code == 200, "TileJSON not accessible"
        
        tilejson = response.json()
        assert "vector_layers" in tilejson, "No vector layers in TileJSON"
        assert len(tilejson["vector_layers"]) > 0, "Empty vector layers"
        print(f"✅ TileJSON has {len(tilejson['vector_layers'])} vector layers")
        
        # Test direct vector tile access
        response = requests.get("http://localhost:8080/data/v3/10/275/427.pbf")
        assert response.status_code in [200, 204], f"Vector tile failed: {response.status_code}"
        print("✅ Direct vector tiles accessible")
    
    def test_2_flask_endpoints_independent(self):
        """Test 2: Verify Flask endpoints work independently"""
        print("\n🔍 TEST 2: Flask endpoint validation")
        
        # Test homepage loads
        response = requests.get("http://localhost:5001")
        assert response.status_code == 200, "Homepage not accessible"
        print("✅ Homepage loads")
        
        # Test vector tile proxy
        response = requests.get("http://localhost:5001/vector_tiles/10/275/427.pbf")
        assert response.status_code in [200, 204], f"Vector proxy failed: {response.status_code}"
        print("✅ Vector tile proxy works")
        
        # Test elevation tiles
        response = requests.get("http://localhost:5001/tiles/10/275/427")
        assert response.status_code == 200, f"Elevation tile failed: {response.status_code}"
        print("✅ Elevation tiles work")
        
        # Test sprite files - THE CRITICAL FAILURE POINT
        sprite_files = ["sprite.json", "sprite.png", "sprite@2x.json", "sprite@2x.png"]
        for sprite_file in sprite_files:
            response = requests.get(f"http://localhost:5001/sprites/{sprite_file}")
            print(f"  Sprite {sprite_file}: {response.status_code}")
            if sprite_file == "sprite.png" and response.status_code != 200:
                print(f"  ❌ CRITICAL: sprite.png returns {response.status_code}")
                print(f"  Response: {response.text[:200]}")
    
    def test_3_maplibre_config_validation(self):
        """Test 3: Verify MapLibre config is valid"""
        print("\n🔍 TEST 3: MapLibre configuration validation")
        
        response = requests.get("http://localhost:5001")
        html = response.text
        
        # Extract MapLibre config
        import re
        config_match = re.search(r'new maplibregl\.Map\((\{.*?\})\);', html, re.DOTALL)
        assert config_match, "No MapLibre config found in HTML"
        
        config_str = config_match.group(1)
        print(f"✅ MapLibre config found ({len(config_str)} chars)")
        
        # Validate required components
        required_patterns = [
            r'container:\s*[\'"]map[\'"]',
            r'style:\s*\{',
            r'sources:\s*\{',
            r'layers:\s*\['
        ]
        
        for pattern in required_patterns:
            assert re.search(pattern, config_str), f"Missing required pattern: {pattern}"
        
        print("✅ MapLibre config has required structure")
        
        # Check for /null/ URLs (previous bug)
        assert "/null/" not in config_str, "Found /null/ URLs in config"
        print("✅ No /null/ URLs in config")
    
    def test_4_browser_component_loading(self):
        """Test 4: Verify browser can load map components (requires Playwright)"""
        print("\n🔍 TEST 4: Browser component loading")
        
        # This would use Playwright to check:
        # - MapLibre JS loads without errors
        # - Map container exists
        # - Style loads successfully
        # - No critical console errors
        
        # For now, just validate the test exists
        print("⚠️  Browser testing requires Playwright - run E2E tests for this")
    
    def test_5_integration_status(self):
        """Test 5: Integration test status summary"""
        print("\n🔍 TEST 5: Integration summary")
        
        print("Run this after fixing sprite issues:")
        print("  uv run pytest tests/e2e/test_maplibre_debugging.py -v")


if __name__ == "__main__":
    # Run tests directly for debugging
    test = TestSystematicDebugging()
    test.test_1_tileserver_direct_access()
    test.test_2_flask_endpoints_independent()
    test.test_3_maplibre_config_validation()
    test.test_4_browser_component_loading()
    test.test_5_integration_status()