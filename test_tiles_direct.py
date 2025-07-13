#!/usr/bin/env python3
"""
Direct test of tile serving without hitting the server.
"""

import os
import asyncio
from fastapi.testclient import TestClient

# Set environment variables
os.environ["INPUT_DIR"] = "scratch/data_tampa"
os.environ["PROCESSED_DIR"] = "scratch/data_tampa_processed"

# Import main after setting env vars
import main

async def test_tile_serving():
    """Test tile serving directly."""
    print("Testing tile serving logic...")
    
    # Test if tile file exists
    tile_path = "scratch/data_tampa_processed/10/275/427.png"
    if os.path.exists(tile_path):
        print(f"✅ Tile file exists: {tile_path}")
        with open(tile_path, 'rb') as f:
            data = f.read()
            print(f"✅ Tile file size: {len(data)} bytes")
    else:
        print(f"❌ Tile file missing: {tile_path}")
        return
    
    # Test the app with TestClient
    client = TestClient(main.app)
    
    print("Testing /healthz endpoint...")
    response = client.get("/healthz")
    print(f"Health check: {response.status_code} - {response.text}")
    
    print("Testing tile endpoint...")
    response = client.get("/tiles/10/275/427")
    print(f"Tile response: {response.status_code}")
    
    if response.status_code == 200:
        print(f"✅ Tile served successfully! Content-Type: {response.headers.get('content-type')}")
        print(f"✅ Tile size: {len(response.content)} bytes")
    else:
        print(f"❌ Tile serving failed: {response.status_code}")
        print(f"Response: {response.text}")
    
    print("Testing homepage...")
    response = client.get("/")
    if response.status_code == 200:
        print("✅ Homepage loaded successfully")
        if "Flood Buddy" in response.text:
            print("✅ Found Flood Buddy title")
        if "Tampa" in response.text:
            print("✅ Found Tampa location info")
    else:
        print(f"❌ Homepage failed: {response.status_code}")

if __name__ == "__main__":
    asyncio.run(test_tile_serving())