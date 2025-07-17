"""Tile serving endpoints - clean and simple."""
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import Response
import httpx
import os
import io
import logging
from PIL import Image
import numpy as np
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from color_mapping import color_mapper
from elevation_loader import elevation_loader
from tile_cache import tile_cache
from error_handling import safe_tile_generation, log_performance, health_monitor

router = APIRouter()
logger = logging.getLogger(__name__)

# Configuration
TILESERVER_PORT = os.getenv("TILESERVER_PORT", "8080")
TILESERVER_URL = f"http://localhost:{TILESERVER_PORT}"

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

@router.get("/tiles/elevation/{water_level}/{z}/{x}/{y}.png")
@safe_tile_generation
@log_performance
async def get_elevation_tile(water_level: float, z: int, x: int, y: int):
    """Generate contextual flood risk tiles dynamically."""
    # Input validation
    if not (8 <= z <= 14):  # Support wider zoom range
        return _transparent_tile()
    
    if not (-10 <= water_level <= 50):  # Reasonable water level range
        raise HTTPException(status_code=400, detail="Invalid water level")
    
    try:
        # Check cache first
        cached_tile = tile_cache.get(water_level, z, x, y)
        if cached_tile is not None:
            return Response(
                content=cached_tile,
                media_type="image/png",
                headers={
                    "Cache-Control": f"public, max-age=3600",
                    "X-Water-Level": str(water_level),
                    "X-Cache": "HIT"
                }
            )
        
        # Load elevation data for this tile
        elevation_data = elevation_loader.get_elevation_for_tile(x, y, z)
        
        if elevation_data is None:
            logger.debug(f"No elevation data for tile {z}/{x}/{y}")
            return _transparent_tile()
        
        # Convert elevation to contextual colors
        rgba_array = color_mapper.elevation_array_to_rgba(
            elevation_data, 
            water_level,
            no_data_value=-32768  # Common SRTM no-data value
        )
        
        # Convert to PIL Image
        img = Image.fromarray(rgba_array, 'RGBA')
        
        # Convert to PNG bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG', optimize=True)
        img_bytes.seek(0)
        
        tile_data = img_bytes.getvalue()
        
        # Cache the generated tile
        tile_cache.put(water_level, z, x, y, tile_data)
        
        return Response(
            content=tile_data,
            media_type="image/png",
            headers={
                "Cache-Control": f"public, max-age=3600",
                "X-Water-Level": str(water_level),
                "X-Cache": "MISS"
            }
        )
        
    except Exception as e:
        logger.error(f"Error generating elevation tile {z}/{x}/{y} at water level {water_level}: {e}")
        return _transparent_tile()


def _transparent_tile() -> Response:
    """Return a transparent PNG tile."""
    transparent_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x07:\xb9Y\x00\x00\x00\x00IEND\xaeB`\x82'
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
    transparent_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x07:\xb9Y\x00\x00\x00\x00IEND\xaeB`\x82'
    return Response(
        content=transparent_png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"}  # Shorter cache for dynamic data
    )