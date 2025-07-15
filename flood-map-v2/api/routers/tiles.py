"""Tile serving endpoints - clean and simple."""
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import Response
import httpx
import os

router = APIRouter()

# Configuration
TILESERVER_URL = "http://localhost:8080"
ELEVATION_DATA_PATH = "../elevation_data.bin"  # Path to existing data

@router.get("/tiles/vector/{z}/{x}/{y}.pbf")
async def get_vector_tile(z: int, x: int, y: int):
    """Serve vector tiles from tileserver."""
    # Input validation
    if not (0 <= z <= 18 and 0 <= x < 2**z and 0 <= y < 2**z):
        raise HTTPException(status_code=400, detail="Invalid tile coordinates")
    
    # Proxy to tileserver
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{TILESERVER_URL}/data/v3/{z}/{x}/{y}.pbf")
            
            if response.status_code == 200:
                return Response(
                    content=response.content,
                    media_type="application/x-protobuf",
                    headers={
                        "Cache-Control": "public, max-age=3600",
                        "Access-Control-Allow-Origin": "*"
                    }
                )
            elif response.status_code == 204:
                # Empty tile
                return Response(
                    content=b"",
                    media_type="application/x-protobuf",
                    headers={"Cache-Control": "public, max-age=3600"}
                )
            else:
                raise HTTPException(status_code=404, detail="Tile not found")
                
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Tileserver unavailable")

@router.get("/tiles/elevation/{z}/{x}/{y}.png")
async def get_elevation_tile(z: int, x: int, y: int):
    """Serve elevation tiles from processed TIF data."""
    # Input validation
    if not (10 <= z <= 12):  # Our elevation data zoom range
        # Return transparent tile for unsupported zoom levels
        transparent_png = b'\\x89PNG\\r\\n\\x1a\\n\\x00\\x00\\x00\\rIHDR\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x01\\x08\\x06\\x00\\x00\\x00\\x1f\\x15\\xc4\\x89\\x00\\x00\\x00\\rIDATx\\x9cc\\xf8\\x0f\\x00\\x00\\x01\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x07:\\xb9Y\\x00\\x00\\x00\\x00IEND\\xaeB`\\x82'
        return Response(
            content=transparent_png,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=3600"}
        )
    
    # Look for elevation tile - use absolute paths to avoid confusion
    base_path = "/Users/davidrose/git/floodmap"
    tile_path = f"{base_path}/processed_data/tiles/{z}/{x}/{y}.png"
    if not os.path.exists(tile_path):
        tile_path = f"{base_path}/flood-map-v2/data/elevation_tiles/{z}/{x}/{y}.png"
    
    if os.path.exists(tile_path):
        try:
            with open(tile_path, "rb") as f:
                tile_content = f.read()
            return Response(
                content=tile_content,
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=3600"}
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading tile: {e}")
    
    # Return transparent tile if no data available
    transparent_png = b'\\x89PNG\\r\\n\\x1a\\n\\x00\\x00\\x00\\rIHDR\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x01\\x08\\x06\\x00\\x00\\x00\\x1f\\x15\\xc4\\x89\\x00\\x00\\x00\\rIDATx\\x9cc\\xf8\\x0f\\x00\\x00\\x01\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x07:\\xb9Y\\x00\\x00\\x00\\x00IEND\\xaeB`\\x82'
    return Response(
        content=transparent_png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"}
    )

@router.get("/tiles/flood/{level}/{z}/{x}/{y}.png")
async def get_flood_tile(level: float, z: int, x: int, y: int):
    """Serve flood risk overlay tiles."""
    # TODO: Implement flood overlay generation
    # For now, return transparent tile
    transparent_png = b'\\x89PNG\\r\\n\\x1a\\n\\x00\\x00\\x00\\rIHDR\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x01\\x08\\x06\\x00\\x00\\x00\\x1f\\x15\\xc4\\x89\\x00\\x00\\x00\\rIDATx\\x9cc\\xf8\\x0f\\x00\\x00\\x01\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x07:\\xb9Y\\x00\\x00\\x00\\x00IEND\\xaeB`\\x82'
    return Response(
        content=transparent_png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"}  # Shorter cache for dynamic data
    )