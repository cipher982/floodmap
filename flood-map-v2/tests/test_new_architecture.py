"""
Test the new clean architecture works properly.
"""
import pytest
import requests
import os


class TestNewArchitecture:
    """Test the clean FastAPI-only architecture."""
    
    BASE_URL = "http://localhost:5002"
    
    def test_health_endpoint(self):
        """Test API health check."""
        response = requests.get(f"{self.BASE_URL}/api/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        print("✅ Health endpoint works")
    
    def test_frontend_loads(self):
        """Test frontend HTML loads."""
        response = requests.get(f"{self.BASE_URL}/")
        assert response.status_code == 200
        assert "Flood Risk Map" in response.text
        assert "maplibre-gl" in response.text
        print("✅ Frontend loads properly")
    
    def test_static_files(self):
        """Test static file serving."""
        # Test CSS
        response = requests.get(f"{self.BASE_URL}/static/css/style.css")
        assert response.status_code == 200
        assert "flood-map-v2" in response.text or "body" in response.text
        
        # Test JS
        response = requests.get(f"{self.BASE_URL}/static/js/map.js")
        assert response.status_code == 200
        assert "FloodMap" in response.text
        print("✅ Static files serve correctly")
    
    def test_api_endpoints_structure(self):
        """Test API endpoint structure."""
        # Test vector tiles endpoint structure (will 404 without tileserver, but should have right format)
        response = requests.get(f"{self.BASE_URL}/api/tiles/vector/10/275/427.pbf")
        # Should either work (200) or fail properly (404/503), not error (500)
        assert response.status_code in [200, 204, 404, 503]
        
        # Test elevation tiles
        response = requests.get(f"{self.BASE_URL}/api/tiles/elevation/8/100/100.png")
        assert response.status_code == 200  # Should return transparent PNG
        assert response.headers.get("content-type") == "image/png"
        
        print("✅ API endpoints have correct structure")
    
    def test_risk_assessment_api(self):
        """Test risk assessment endpoints."""
        # Test location-based risk
        payload = {"latitude": 27.9506, "longitude": -82.4572}
        response = requests.post(f"{self.BASE_URL}/api/risk/location", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert "flood_risk_level" in data
        assert "elevation_m" in data
        
        # Test IP-based risk
        response = requests.get(f"{self.BASE_URL}/api/risk/ip")
        assert response.status_code == 200
        print("✅ Risk assessment API works")


if __name__ == "__main__":
    # Run tests directly
    test = TestNewArchitecture()
    test.test_health_endpoint()
    test.test_frontend_loads()
    test.test_static_files()
    test.test_api_endpoints_structure()
    test.test_risk_assessment_api()
    
    print("\n🎉 All architecture tests passed!")
    print("New clean architecture is working correctly.")