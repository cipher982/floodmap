#!/usr/bin/env python3
"""Debug script to test vector tile proxy endpoint."""

import asyncio
import httpx

async def test_vector_tile_proxy():
    """Test the vector tile proxy endpoint directly."""
    
    print("🔍 Testing vector tile proxy endpoint...")
    
    async with httpx.AsyncClient() as client:
        try:
            # Test the proxy endpoint
            print("Testing proxy: /vector_tiles/10/275/427.pbf")
            response = await client.get("http://localhost:5001/vector_tiles/10/275/427.pbf")
            
            print(f"Status: {response.status_code}")
            print(f"Headers: {dict(response.headers)}")
            
            if response.status_code >= 400:
                print(f"Error response: {response.text}")
            
            # Test the direct tileserver  
            print("\nTesting direct tileserver: /data/tampa/10/275/427.pbf")
            direct_response = await client.get("http://localhost:8080/data/tampa/10/275/427.pbf")
            
            print(f"Status: {direct_response.status_code}")
            print(f"Headers: {dict(direct_response.headers)}")
            
            if direct_response.status_code >= 400:
                print(f"Error response: {direct_response.text}")
                
        except Exception as e:
            print(f"Error during testing: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_vector_tile_proxy())