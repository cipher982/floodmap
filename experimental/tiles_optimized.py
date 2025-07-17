"""Optimized tile serving with async processing and smart caching."""
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import Response
import httpx
import os
import io
import logging
from PIL import Image
import numpy as np
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from color_mapping import color_mapper
from elevation_loader_optimized import optimized_elevation_loader
from error_handling import safe_tile_generation, log_performance, health_monitor

router = APIRouter()
logger = logging.getLogger(__name__)

# Configuration
TILESERVER_PORT = os.getenv("TILESERVER_PORT", "8080")
TILESERVER_URL = f"http://localhost:{TILESERVER_PORT}"

# Thread pool for CPU-intensive work
CPU_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tile-cpu")

# Smart cache with water level clustering
class SmartTileCache:
    """Cache that clusters similar water levels to improve hit rates."""
    
    def __init__(self, max_size: int = 2000):
        self.cache = {}
        self.max_size = max_size
        self.access_order = []
        
    def _cluster_water_level(self, water_level: float) -> float:
        """Cluster water levels to 0.5m increments for better cache hits."""
        return round(water_level * 2) / 2  # Round to nearest 0.5
    
    def _make_key(self, water_level: float, z: int, x: int, y: int) -> str:
        clustered_level = self._cluster_water_level(water_level)
        return f"{clustered_level:.1f}:{z}:{x}:{y}"
    
    def get(self, water_level: float, z: int, x: int, y: int) -> bytes:
        key = self._make_key(water_level, z, x, y)
        if key in self.cache:
            # Move to end for LRU
            self.access_order.remove(key)
            self.access_order.append(key)
            return self.cache[key]
        return None
    
    def put(self, water_level: float, z: int, x: int, y: int, tile_data: bytes):
        key = self._make_key(water_level, z, x, y)
        
        # Evict if full
        while len(self.cache) >= self.max_size and self.access_order:
            oldest_key = self.access_order.pop(0)
            if oldest_key in self.cache:
                del self.cache[oldest_key]
        
        self.cache[key] = tile_data
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)

# Global smart cache
smart_cache = SmartTileCache()

def generate_elevation_tile_sync(water_level: float, z: int, x: int, y: int) -> bytes:
    """Synchronous tile generation for thread pool execution."""
    try:
        # Load elevation data (optimized)
        elevation_data = optimized_elevation_loader.get_elevation_for_tile(x, y, z)
        
        if elevation_data is None:
            return _transparent_tile_bytes()
        
        # Convert elevation to contextual colors (vectorized)
        rgba_array = color_mapper.elevation_array_to_rgba(
            elevation_data, 
            water_level,
            no_data_value=-32768
        )
        
        # Convert to PNG bytes (optimized)
        img = Image.fromarray(rgba_array, 'RGBA')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG', optimize=True, compress_level=1)  # Fast compression
        return img_bytes.getvalue()
        
    except Exception as e:
        logger.error(f"Error generating tile {z}/{x}/{y} at water level {water_level}: {e}")
        return _transparent_tile_bytes()

def _transparent_tile_bytes() -> bytes:
    """Return transparent PNG as bytes."""
    return b'\\x89PNG\\r\\n\\x1a\\n\\x00\\x00\\x00\\rIHDR\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x01\\x08\\x06\\x00\\x00\\x00\\x1f\\x15\\xc4\\x89\\x00\\x00\\x00\\rIDATx\\x9cc\\xf8\\x0f\\x00\\x00\\x01\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x07:\\xb9Y\\x00\\x00\\x00\\x00IEND\\xaeB`\\x82'

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
async def get_elevation_tile_optimized(water_level: float, z: int, x: int, y: int):
    """OPTIMIZED elevation tile generation with async processing."""
    # Input validation
    if not (8 <= z <= 14):
        return Response(
            content=_transparent_tile_bytes(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=3600"}
        )
    
    if not (-10 <= water_level <= 50):
        raise HTTPException(status_code=400, detail="Invalid water level")
    
    # Check smart cache first
    cached_tile = smart_cache.get(water_level, z, x, y)
    if cached_tile is not None:
        return Response(
            content=cached_tile,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Water-Level": str(water_level),
                "X-Cache": "HIT"
            }
        )
    
    # Generate tile asynchronously
    loop = asyncio.get_event_loop()
    tile_data = await loop.run_in_executor(
        CPU_EXECUTOR,
        generate_elevation_tile_sync,
        water_level, z, x, y
    )
    
    # Cache the generated tile
    smart_cache.put(water_level, z, x, y, tile_data)
    
    return Response(
        content=tile_data,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Water-Level": str(water_level),
            "X-Cache": "MISS"
        }
    )

def _transparent_tile() -> Response:
    """Return a transparent PNG tile."""
    return Response(
        content=_transparent_tile_bytes(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"}
    )

@router.get("/tiles/flood/{level}/{z}/{x}/{y}.png")
async def get_flood_tile(level: float, z: int, x: int, y: int):
    """Serve flood risk overlay tiles."""
    # TODO: Implement flood overlay generation
    return _transparent_tile()