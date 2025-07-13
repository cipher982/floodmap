#!/usr/bin/env python3
"""
Debug flood overlay generation.
"""

import os
from fastapi.testclient import TestClient

# Set environment variables
os.environ["INPUT_DIR"] = "scratch/data_tampa"
os.environ["PROCESSED_DIR"] = "scratch/data_tampa_processed"

# Import main after setting env vars
import main

def test_flood_generation():
    """Test flood overlay generation with different water levels."""
    
    client = TestClient(main.app)
    
    print("🔍 Testing flood overlay generation...")
    
    # First check elevation at debug coordinates
    print(f"Debug coordinates: {main.DEBUG_COORDS}")
    elevation = main.get_elevation(main.DEBUG_COORDS[0], main.DEBUG_COORDS[1])
    print(f"Elevation at debug coordinates: {elevation} meters")
    
    # Test different water levels
    water_levels = [1, 5, 10, 15, 18, 20, 25, 50]
    
    for water_level in water_levels:
        print(f"\n💧 Testing water level: {water_level}m")
        
        # Test risk assessment
        risk_response = client.get(f"/risk/{water_level}")
        if risk_response.status_code == 200:
            risk_data = risk_response.json()
            print(f"  Risk status: {risk_data['status']} (elevation: {risk_data['elevation_m']}m)")
        
        # Test flood tile generation for Tampa area
        tile_coords = [
            (10, 275, 427),  # Tampa area tiles
            (10, 276, 428),
            (11, 551, 854)
        ]
        
        for z, x, y in tile_coords:
            flood_response = client.get(f"/flood_tiles/{water_level}/{z}/{x}/{y}")
            status = flood_response.status_code
            
            if status == 200:
                print(f"  ✅ Flood tile {z}/{x}/{y}: Generated ({len(flood_response.content)} bytes)")
            elif status == 204:
                print(f"  ⚪ Flood tile {z}/{x}/{y}: No flood area (204)")
            elif status == 400:
                print(f"  ❌ Flood tile {z}/{x}/{y}: Bad request (400)")
            else:
                print(f"  ❌ Flood tile {z}/{x}/{y}: Error {status}")
    
    print("\n🌐 Testing homepage with flood overlay...")
    
    # Test homepage with different water levels
    homepage_tests = [1.0, 10.0, 20.0]
    
    for water_level in homepage_tests:
        print(f"\n🏠 Homepage with water level {water_level}m:")
        
        response = client.get(f"/?water_level={water_level}")
        if response.status_code == 200:
            content = response.text
            
            # Check if flood overlay is configured in the map
            if f"flood_tiles/{water_level}/" in content:
                print(f"  ✅ Flood overlay configured for {water_level}m")
            else:
                print(f"  ❌ Flood overlay not found in HTML for {water_level}m")
            
            # Check map configuration
            if "floodLayer" in content:
                print(f"  ✅ Flood layer JavaScript found")
            else:
                print(f"  ❌ Flood layer JavaScript missing")
                
            if "overlayMapTypes.insertAt" in content:
                print(f"  ✅ Overlay insertion code found")
            else:
                print(f"  ❌ Overlay insertion code missing")

if __name__ == "__main__":
    test_flood_generation()