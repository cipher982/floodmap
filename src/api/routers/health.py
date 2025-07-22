"""Health check endpoints."""
from fastapi import APIRouter
from datetime import datetime
import os
from pathlib import Path

# Import health monitor if available
try:
    from error_handling import health_monitor
    HEALTH_MONITORING = True
except ImportError:
    HEALTH_MONITORING = False

# Import cache for statistics
try:
    from tile_cache import tile_cache
    CACHE_STATS = True
except ImportError:
    CACHE_STATS = False

# Import multi-core systems for statistics
try:
    from persistent_elevation_cache import persistent_elevation_cache
    from predictive_preloader import predictive_preloader
    MULTICORE_STATS = True
except ImportError:
    MULTICORE_STATS = False

router = APIRouter()

@router.get("/health")
async def health_check():
    """Comprehensive health check endpoint."""
    health_data = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "flood-map-api",
        "version": "2.0.0"
    }
    
    # Add monitoring data if available
    if HEALTH_MONITORING:
        stats = health_monitor.get_stats()
        health_data.update({
            "uptime_seconds": stats["uptime_seconds"],
            "tile_requests": stats["tile_requests"],
            "error_rate": stats["error_rate"],
            "cache_hit_rate": stats["cache_hit_rate"],
            "requests_per_second": stats["requests_per_second"]
        })
        
        # Update status based on health
        if not health_monitor.is_healthy():
            health_data["status"] = "unhealthy"
    
    # Check elevation data availability
    elevation_data_dir = Path("/Users/davidrose/git/floodmap/compressed_data/usa")
    if elevation_data_dir.exists():
        elevation_files = list(elevation_data_dir.glob("*.zst"))
        health_data["elevation_files_available"] = len(elevation_files)
    else:
        health_data["elevation_files_available"] = 0
        if health_data["status"] == "healthy":
            health_data["status"] = "degraded"
    
    # Check map data availability
    map_data_dir = Path("/Users/davidrose/git/floodmap/map_data")
    if map_data_dir.exists():
        mbtiles_files = list(map_data_dir.glob("*.mbtiles"))
        regional_files = list((map_data_dir / "regions").glob("*.mbtiles")) if (map_data_dir / "regions").exists() else []
        health_data["map_tiles_available"] = len(mbtiles_files) + len(regional_files)
    else:
        health_data["map_tiles_available"] = 0
    
    return health_data

@router.get("/metrics")
async def get_metrics():
    """Get detailed system metrics."""
    stats = {}
    
    if HEALTH_MONITORING:
        stats.update(health_monitor.get_stats())
    
    # Add system information
    stats.update({
        "memory_usage_mb": _get_memory_usage(),
        "disk_usage": _get_disk_usage(),
        "system_load": _get_system_load()
    })
    
    # Add cache statistics
    if CACHE_STATS:
        stats["cache"] = tile_cache.stats()
    
    # Add multi-core system statistics
    if MULTICORE_STATS:
        stats["elevation_cache"] = persistent_elevation_cache.get_stats()
        stats["predictive_preloader"] = predictive_preloader.get_stats()
    
    return stats

@router.get("/cache")
async def get_cache_stats():
    """Get tile cache statistics."""
    if not CACHE_STATS:
        return {"error": "Cache statistics not available"}
    
    return tile_cache.stats()

@router.get("/status")
async def detailed_status():
    """Legacy detailed status endpoint."""
    return {
        "api": "running",
        "elevation_data": "loaded",
        "vector_tiles": "available",
        "timestamp": datetime.utcnow().isoformat()
    }

def _get_memory_usage() -> float:
    """Get current memory usage in MB."""
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024
    except ImportError:
        return 0.0

def _get_disk_usage() -> dict:
    """Get disk usage for key directories."""
    usage = {}
    
    key_dirs = [
        "/Users/davidrose/git/floodmap/compressed_data",
        "/Users/davidrose/git/floodmap/map_data"
    ]
    
    for dir_path in key_dirs:
        if os.path.exists(dir_path):
            try:
                import shutil
                total, used, free = shutil.disk_usage(dir_path)
                usage[dir_path] = {
                    "total_gb": total / (1024**3),
                    "used_gb": used / (1024**3), 
                    "free_gb": free / (1024**3)
                }
            except Exception:
                pass
    
    return usage

def _get_system_load() -> dict:
    """Get system load information."""
    try:
        import psutil
        return {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_percent": psutil.virtual_memory().percent
        }
    except ImportError:
        return {}