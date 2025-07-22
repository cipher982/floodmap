"""
Comprehensive error handling and fallback systems for flood map API.
"""

import logging
import time
import functools
from typing import Optional, Any, Callable
from fastapi import HTTPException, Response
import numpy as np
from PIL import Image
import io

logger = logging.getLogger(__name__)


class FloodMapError(Exception):
    """Base exception for flood map errors."""
    pass


class ElevationDataError(FloodMapError):
    """Elevation data related errors."""
    pass


class TileGenerationError(FloodMapError):
    """Tile generation related errors."""
    pass


def retry_with_backoff(max_retries: int = 3, backoff_factor: float = 1.0):
    """Decorator to retry functions with exponential backoff."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt < max_retries - 1:
                        sleep_time = backoff_factor * (2 ** attempt)
                        logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}. Retrying in {sleep_time}s...")
                        time.sleep(sleep_time)
                    else:
                        logger.error(f"All {max_retries} attempts failed for {func.__name__}: {e}")
            
            raise last_exception
        return wrapper
    return decorator


def safe_elevation_loading(func: Callable) -> Callable:
    """Decorator to safely handle elevation data loading with fallbacks."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Elevation loading failed in {func.__name__}: {e}")
            # Return None to indicate no data available
            return None
    return wrapper


def create_fallback_tile(tile_size: int = 256, color: tuple = (128, 128, 128, 64)) -> bytes:
    """Create a fallback tile when elevation data is unavailable."""
    try:
        # Create a subtle gray tile to indicate no data
        img = Image.new('RGBA', (tile_size, tile_size), color)
        
        # Add a subtle pattern to indicate this is a fallback
        # Draw a small dot in the center
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        center = tile_size // 2
        draw.ellipse([center-2, center-2, center+2, center+2], fill=(100, 100, 100, 128))
        
        # Convert to bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG', optimize=True)
        img_bytes.seek(0)
        
        return img_bytes.getvalue()
    except Exception as e:
        logger.error(f"Failed to create fallback tile: {e}")
        # Return minimal transparent PNG
        return b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x07:\xb9Y\x00\x00\x00\x00IEND\xaeB`\x82'


def validate_tile_coordinates(z: int, x: int, y: int) -> bool:
    """Validate tile coordinates are within reasonable bounds."""
    if not (0 <= z <= 20):  # Reasonable zoom range
        return False
    
    max_coord = 2 ** z
    if not (0 <= x < max_coord and 0 <= y < max_coord):
        return False
    
    return True


def validate_water_level(water_level: float) -> bool:
    """Validate water level is within reasonable bounds."""
    return -50 <= water_level <= 100  # -50m to 100m seems reasonable


def safe_tile_generation(func: Callable) -> Callable:
    """Decorator to safely handle tile generation with comprehensive fallbacks."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            # Extract common parameters for validation
            if 'z' in kwargs:
                z, x, y = kwargs['z'], kwargs['x'], kwargs['y']
            else:
                # Assume positional arguments
                z, x, y = args[1], args[2], args[3]  # Skip 'self' or first arg
            
            water_level = kwargs.get('water_level', args[0] if args else 1.0)
            
            # Validate inputs
            if not validate_tile_coordinates(z, x, y):
                logger.warning(f"Invalid tile coordinates: {z}/{x}/{y}")
                return Response(
                    content=create_fallback_tile(),
                    media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600", "X-Error": "Invalid coordinates"}
                )
            
            if not validate_water_level(water_level):
                logger.warning(f"Invalid water level: {water_level}")
                return Response(
                    content=create_fallback_tile(),
                    media_type="image/png", 
                    headers={"Cache-Control": "public, max-age=3600", "X-Error": "Invalid water level"}
                )
            
            # Call the original function
            result = await func(*args, **kwargs)
            
            # Validate result
            if result is None:
                logger.warning(f"Tile generation returned None for {z}/{x}/{y}")
                return Response(
                    content=create_fallback_tile(),
                    media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600", "X-Error": "No data"}
                )
            
            return result
            
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            logger.error(f"Tile generation failed for {args[1:]}: {e}", exc_info=True)
            
            # Return fallback tile instead of error
            return Response(
                content=create_fallback_tile(color=(180, 100, 100, 96)),  # Slightly red to indicate error
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=300", "X-Error": "Generation failed"}  # Shorter cache for errors
            )
    
    return wrapper


def log_performance(func: Callable) -> Callable:
    """Decorator to log performance metrics for optimization."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        
        try:
            result = await func(*args, **kwargs)
            duration = time.time() - start_time
            
            # Log slow operations
            if duration > 1.0:  # Slower than 1 second
                logger.warning(f"{func.__name__} took {duration:.2f}s (slow)")
            elif duration > 0.5:  # Slower than 500ms
                logger.info(f"{func.__name__} took {duration:.2f}s")
            
            return result
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"{func.__name__} failed after {duration:.2f}s: {e}")
            raise
    
    return wrapper


class HealthMonitor:
    """Monitor system health and provide diagnostics."""
    
    def __init__(self):
        self.tile_requests = 0
        self.tile_errors = 0
        self.elevation_cache_hits = 0
        self.elevation_cache_misses = 0
        self.start_time = time.time()
    
    def record_tile_request(self, success: bool = True):
        """Record a tile request."""
        self.tile_requests += 1
        if not success:
            self.tile_errors += 1
    
    def record_cache_hit(self, hit: bool = True):
        """Record cache hit/miss."""
        if hit:
            self.elevation_cache_hits += 1
        else:
            self.elevation_cache_misses += 1
    
    def get_stats(self) -> dict:
        """Get current system statistics."""
        uptime = time.time() - self.start_time
        error_rate = self.tile_errors / max(self.tile_requests, 1)
        cache_hit_rate = self.elevation_cache_hits / max(self.elevation_cache_hits + self.elevation_cache_misses, 1)
        
        return {
            "uptime_seconds": uptime,
            "tile_requests": self.tile_requests,
            "tile_errors": self.tile_errors,
            "error_rate": error_rate,
            "cache_hit_rate": cache_hit_rate,
            "requests_per_second": self.tile_requests / uptime if uptime > 0 else 0
        }
    
    def is_healthy(self) -> bool:
        """Check if system is healthy."""
        stats = self.get_stats()
        
        # System is unhealthy if:
        # - Error rate > 50%
        # - No requests processed in last 5 minutes (if any requests made)
        if stats["error_rate"] > 0.5:
            return False
        
        return True


# Global health monitor
health_monitor = HealthMonitor()