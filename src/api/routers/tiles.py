"""Tile serving endpoints - clean and simple."""
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import Response
import httpx
import os
import io
import logging
from PIL import Image
import numpy as np
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from color_mapping import color_mapper
from elevation_loader import elevation_loader
import zstandard as zstd
import json
from tile_cache import tile_cache
from error_handling import safe_tile_generation, log_performance, health_monitor
from persistent_elevation_cache import persistent_elevation_cache
from predictive_preloader import predictive_preloader

router = APIRouter()
logger = logging.getLogger(__name__)

# Configuration
TILESERVER_PORT = os.getenv("TILESERVER_PORT", "8080")
TILESERVER_URL = f"http://localhost:{TILESERVER_PORT}"

# Thread pool for CPU-intensive tile generation
CPU_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tile-cpu")


def generate_elevation_tile_sync(water_level: float, z: int, x: int, y: int) -> bytes:
    """OPTIMIZED synchronous tile generation using persistent cache."""
    try:
        # Use persistent elevation cache instead of slow elevation_loader
        # This eliminates the 23ms zstd decompression bottleneck
        
        # CARMACK-STYLE FIX: Use existing mosaicking code instead of 24x24 sampling
        # This eliminates the 576 individual point samples and uses the proper
        # vectorized mosaicking that already handles coordinate transformation correctly
        
        elevation_data = elevation_loader.get_elevation_for_tile(x, y, z, tile_size=256)
        
        # Handle case where no elevation data is available
        if elevation_data is None:
            logger.warning(f"No elevation data available for tile {z}/{x}/{y}")
            # Return transparent tile
            return b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x07:\xb9Y\x00\x00\x00\x00IEND\xaeB`\x82'
        
        # Convert elevation to contextual colors
        rgba_array = color_mapper.elevation_array_to_rgba(
            elevation_data, 
            water_level,
            no_data_value=-32768  # Common SRTM no-data value
        )
        
        # Convert to PIL Image
        img = Image.fromarray(rgba_array, 'RGBA')
        
        # Convert to PNG bytes with fast compression
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG', optimize=True, compress_level=1)  # Fast compression
        img_bytes.seek(0)
        
        return img_bytes.getvalue()
        
    except Exception as e:
        logger.error(f"Error generating elevation tile {z}/{x}/{y} at water level {water_level}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Elevation tile generation failed: {str(e)}"
        )

def generate_topographical_tile_sync(z: int, x: int, y: int) -> bytes:
    """Generate topographical tile showing absolute elevation colors."""
    try:
        # Get elevation data using the same optimized mosaicking
        elevation_data = elevation_loader.get_elevation_for_tile(x, y, z, tile_size=256)
        
        # Handle case where no elevation data is available
        if elevation_data is None:
            logger.warning(f"No elevation data available for topographical tile {z}/{x}/{y}")
            # Return transparent tile
            return b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x07:\xb9Y\x00\x00\x00\x00IEND\xaeB`\x82'
        
        # Convert elevation to topographical colors (absolute elevation)
        rgba_array = color_mapper.elevation_array_to_topographical_rgba(
            elevation_data, 
            no_data_value=-32768  # Common SRTM no-data value
        )
        
        # Convert to PIL Image
        img = Image.fromarray(rgba_array, 'RGBA')
        
        # Convert to PNG bytes with fast compression
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG', optimize=True, compress_level=1)  # Fast compression
        img_bytes.seek(0)
        
        return img_bytes.getvalue()
        
    except Exception as e:
        logger.error(f"Error generating topographical tile {z}/{x}/{y}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Topographical tile generation failed: {str(e)}"
        )

@router.get("/tiles/topographical/{z}/{x}/{y}.png")
@log_performance
async def get_topographical_tile(z: int, x: int, y: int):
    """Generate topographical tiles showing absolute elevation colors."""
    # Input validation
    if not (0 <= z <= 18 and 0 <= x < 2**z and 0 <= y < 2**z):
        raise HTTPException(status_code=400, detail="Invalid tile coordinates")
    
    try:
        # Check cache first (using special cache key for topographical tiles)
        cache_key_water_level = -888.0  # Special value for topographical tiles
        cached_tile = tile_cache.get(cache_key_water_level, z, x, y)
        if cached_tile is not None:
            return Response(
                content=cached_tile,
                media_type="image/png",
                headers={
                    "Cache-Control": f"public, max-age=3600",
                    "X-Tile-Type": "topographical",
                    "X-Cache": "HIT"
                }
            )
        
        # Generate tile asynchronously using thread pool
        loop = asyncio.get_event_loop()
        tile_data = await loop.run_in_executor(
            CPU_EXECUTOR,
            generate_topographical_tile_sync,
            z, x, y
        )
        
        # Cache the generated tile
        tile_cache.put(cache_key_water_level, z, x, y, tile_data)
        
        return Response(
            content=tile_data,
            media_type="image/png",
            headers={
                "Cache-Control": f"public, max-age=3600",
                "X-Tile-Type": "topographical",
                "X-Cache": "MISS"
            }
        )
        
    except Exception as e:
        logger.error(f"Error generating topographical tile {z}/{x}/{y}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Topographical tile generation failed: {str(e)}"
        )

def _transparent_tile_bytes() -> bytes:
    """Return transparent PNG as bytes."""
    return b'\\x89PNG\\r\\n\\x1a\\n\\x00\\x00\\x00\\rIHDR\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x01\\x08\\x06\\x00\\x00\\x00\\x1f\\x15\\xc4\\x89\\x00\\x00\\x00\\rIDATx\\x9cc\\xf8\\x0f\\x00\\x00\\x01\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x07:\\xb9Y\\x00\\x00\\x00\\x00IEND\\xaeB`\\x82'

@router.get("/tiles/vector/{z}/{x}/{y}.pbf")
async def get_vector_tile(z: int, x: int, y: int):
    """Serve vector tiles from tileserver."""
    # Input validation
    if not (0 <= z <= 18 and 0 <= x < 2**z and 0 <= y < 2**z):
        raise HTTPException(status_code=400, detail="Invalid tile coordinates")
    
    # Proxy to tileserver with fallback logic
    async with httpx.AsyncClient() as client:
        try:
            # Use Tampa as primary source (usa-complete is corrupted)
            response = await client.get(f"{TILESERVER_URL}/data/tampa/{z}/{x}/{y}.pbf")
            
            if response.status_code == 200 and len(response.content) > 0:
                return Response(
                    content=response.content,
                    media_type="application/x-protobuf",
                    headers={
                        "Cache-Control": "public, max-age=3600",
                        "Access-Control-Allow-Origin": "*",
                        "X-Tile-Source": "tampa"
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
@log_performance
async def get_elevation_tile(water_level: float, z: int, x: int, y: int):
    """Generate contextual flood risk tiles dynamically with async processing."""
    # No zoom restrictions - elevation data works at any zoom level
    
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
        
        # Record request for predictive preloading
        predictive_preloader.record_tile_request(z, x, y, water_level)
        
        # Generate tile asynchronously using thread pool
        loop = asyncio.get_event_loop()
        tile_data = await loop.run_in_executor(
            CPU_EXECUTOR,
            generate_elevation_tile_sync,
            water_level, z, x, y
        )
        
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
        raise HTTPException(
            status_code=500,
            detail=f"Elevation tile generation failed: {str(e)}"
        )


def _transparent_tile() -> Response:
    """Return a transparent PNG tile."""
    transparent_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x07:\xb9Y\x00\x00\x00\x00IEND\xaeB`\x82'
    return Response(
        content=transparent_png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"}
    )

@router.post("/tiles/bulk")
async def generate_bulk_tiles(tile_requests: List[dict]):
    """
    Generate multiple tiles efficiently using all available cores.
    Request format: [{"z": 11, "x": 555, "y": 859, "water_level": 2.0}, ...]
    """
    
    if len(tile_requests) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 tiles per bulk request")
    
    # Process all tiles concurrently
    async def generate_single_tile(req: dict):
        try:
            z, x, y = req["z"], req["x"], req["y"]
            water_level = req["water_level"]
            
            # Check cache first
            cached_tile = tile_cache.get(water_level, z, x, y)
            if cached_tile is not None:
                return {
                    "z": z, "x": x, "y": y, "water_level": water_level,
                    "status": "cached", "size": len(cached_tile)
                }
            
            # Generate tile
            loop = asyncio.get_event_loop()
            tile_data = await loop.run_in_executor(
                CPU_EXECUTOR,
                generate_elevation_tile_sync,
                water_level, z, x, y
            )
            
            # Cache the result
            tile_cache.put(water_level, z, x, y, tile_data)
            
            return {
                "z": z, "x": x, "y": y, "water_level": water_level,
                "status": "generated", "size": len(tile_data)
            }
            
        except Exception as e:
            return {
                "z": req.get("z"), "x": req.get("x"), "y": req.get("y"), 
                "water_level": req.get("water_level"),
                "status": "error", "error": str(e)
            }
    
    # Execute all tile generations concurrently
    start_time = time.time()
    results = await asyncio.gather(*[generate_single_tile(req) for req in tile_requests])
    end_time = time.time()
    
    # Calculate statistics
    successful = [r for r in results if r["status"] in ["generated", "cached"]]
    cached = [r for r in results if r["status"] == "cached"]
    
    return {
        "tiles_processed": len(results),
        "successful": len(successful),
        "cached": len(cached),
        "generated": len(successful) - len(cached),
        "failed": len(results) - len(successful),
        "processing_time_ms": (end_time - start_time) * 1000,
        "tiles_per_second": len(results) / max(end_time - start_time, 0.001),
        "results": results
    }

@router.get("/tiles/flood/{level}/{z}/{x}/{y}.png")
async def get_flood_tile(level: float, z: int, x: int, y: int):
    """Serve flood risk overlay tiles."""
    # TODO: Implement flood overlay generation
    # For now, return transparent tile
    return _transparent_tile()

@router.get("/debug/coverage")
async def debug_coverage():
    """Debug endpoint to check data coverage."""
    from pathlib import Path
    import sqlite3
    
    # Check elevation data coverage
    elevation_dirs = [
        Path("/Users/davidrose/git/floodmap/compressed_data/usa"),
        Path("/Users/davidrose/git/floodmap/compressed_data/usa_unified"),
        Path("/Users/davidrose/git/floodmap/compressed_data/tampa")
    ]
    
    elevation_coverage = {}
    for dir_path in elevation_dirs:
        if dir_path.exists():
            files = list(dir_path.glob("*.zst"))
            elevation_coverage[dir_path.name] = {
                "files": len(files),
                "size_gb": sum(f.stat().st_size for f in files) / (1024**3)
            }
    
    # Check vector tile coverage
    vector_files = [
        Path("/Users/davidrose/git/floodmap/map_data/usa-complete.mbtiles"),
        Path("/Users/davidrose/git/floodmap/map_data/tampa.mbtiles")
    ]
    
    vector_coverage = {}
    for file_path in vector_files:
        if file_path.exists():
            size_mb = file_path.stat().st_size / (1024**2)
            vector_coverage[file_path.name] = {"size_mb": size_mb}
            
            # Check if it's a valid SQLite database
            try:
                conn = sqlite3.connect(str(file_path))
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                cursor.execute("SELECT COUNT(*) FROM tiles")
                tile_count = cursor.fetchone()[0]
                conn.close()
                
                vector_coverage[file_path.name].update({
                    "valid": True,
                    "tables": tables,
                    "tile_count": tile_count
                })
            except Exception as e:
                vector_coverage[file_path.name].update({
                    "valid": False,
                    "error": str(e)
                })
    
    return {
        "elevation_coverage": elevation_coverage,
        "vector_coverage": vector_coverage,
        "current_config": {
            "tileserver_url": TILESERVER_URL,
            "elevation_zoom_range": "8-14",
            "vector_source": "usa-complete (primary), tampa (fallback)"
        }
    }

@router.get("/debug/tile/{z}/{x}/{y}")
async def debug_tile(z: int, x: int, y: int):
    """Debug specific tile - check what data is available."""
    from pathlib import Path
    
    # Get tile bounds
    lat_top, lat_bottom, lon_left, lon_right = elevation_loader.num2deg(x, y, z)
    
    # Check elevation data availability
    elevation_files = elevation_loader.find_elevation_files_for_tile(
        lat_top, lat_bottom, lon_left, lon_right
    )
    
    elevation_info = {
        "bounds": {
            "lat_top": lat_top,
            "lat_bottom": lat_bottom, 
            "lon_left": lon_left,
            "lon_right": lon_right
        },
        "elevation_files": [str(f) for f in elevation_files] if elevation_files else [],
        "has_elevation": len(elevation_files) > 0
    }
    
    # Check vector tile availability
    vector_info = {}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{TILESERVER_URL}/data/usa-complete/{z}/{x}/{y}.pbf")
            vector_info["usa_complete"] = {
                "status": response.status_code,
                "size": len(response.content) if response.content else 0
            }
        except Exception as e:
            vector_info["usa_complete"] = {"error": str(e)}
        
        try:
            response = await client.get(f"{TILESERVER_URL}/data/tampa/{z}/{x}/{y}.pbf")
            vector_info["tampa"] = {
                "status": response.status_code,
                "size": len(response.content) if response.content else 0
            }
        except Exception as e:
            vector_info["tampa"] = {"error": str(e)}
    
    return {
        "tile": f"{z}/{x}/{y}",
        "elevation": elevation_info,
        "vector": vector_info
    }