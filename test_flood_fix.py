#!/usr/bin/env python3
"""
Test that flood overlay fix is working - simplified verification.
"""

import requests
import time
import subprocess

def test_flood_overlay_fix():
    """Test that flood overlay URLs are properly configured."""
    
    # Start server
    print("Starting server...")
    process = subprocess.Popen(
        ["uv", "run", "python", "main.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for server to start
    for i in range(15):
        try:
            response = requests.get("http://localhost:5001/healthz", timeout=2)
            if response.status_code == 200:
                print("Server is ready!")
                break
        except requests.exceptions.RequestException:
            time.sleep(1)
    else:
        process.terminate()
        raise RuntimeError("Server failed to start")
    
    try:
        # Test homepage with water level parameter
        print("\nTesting flood overlay configuration...")
        
        response = requests.get("http://localhost:5001/?water_level=10", timeout=5)
        if response.status_code == 200:
            content = response.text
            
            # Check if flood overlay URL is correctly interpolated
            if "/flood_tiles/10/" in content:
                print("✅ Flood overlay URL correctly configured for 10m water level")
            else:
                print("❌ Flood overlay URL not found")
                
            # Check for key JavaScript elements
            if "floodLayer" in content:
                print("✅ Flood layer JavaScript found")
            else:
                print("❌ Flood layer JavaScript missing")
                
            if "coord.x" in content and "coord.y" in content:
                print("✅ JavaScript coordinate variables found")
            else:
                print("❌ JavaScript coordinate variables missing")
        
        # Test flood tile endpoint directly
        print("\nTesting flood tile endpoints...")
        
        flood_response = requests.get("http://localhost:5001/flood_tiles/10/10/275/427", timeout=5)
        if flood_response.status_code == 200:
            print(f"✅ Flood tile (10m) generated successfully - {len(flood_response.content)} bytes")
        elif flood_response.status_code == 204:
            print("⚪ Flood tile (10m) returns 204 - no flood at this level")
        else:
            print(f"❌ Flood tile (10m) failed: {flood_response.status_code}")
            
        # Test higher water level
        flood_high = requests.get("http://localhost:5001/flood_tiles/25/10/275/427", timeout=5)
        if flood_high.status_code == 200:
            print(f"✅ High flood tile (25m) generated successfully - {len(flood_high.content)} bytes")
        elif flood_high.status_code == 204:
            print("⚪ High flood tile (25m) returns 204 - no flood at this level")
        else:
            print(f"❌ High flood tile (25m) failed: {flood_high.status_code}")
        
        print("\n🎉 Flood overlay fix verification completed!")
        
    finally:
        # Cleanup
        process.terminate()
        process.wait()

if __name__ == "__main__":
    test_flood_overlay_fix()