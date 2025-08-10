"""Health check endpoints."""
from fastapi import APIRouter
from datetime import datetime
import os
from pathlib import Path

from config import ELEVATION_DATA_DIR, MAP_DATA_DIR, HEALTH_CHECK_DIRS

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
    
    # Check elevation data availability with detailed validation
    if ELEVATION_DATA_DIR.exists():
        elevation_files = list(ELEVATION_DATA_DIR.glob("*.zst"))
        health_data["elevation_files_available"] = len(elevation_files)
        
        # Critical data validation
        if len(elevation_files) < 1000:
            health_data["status"] = "critical"
            health_data["errors"] = health_data.get("errors", [])
            health_data["errors"].append(f"Critical: Only {len(elevation_files)} elevation files (expected 2000+)")
        elif len(elevation_files) < 2000:
            if health_data["status"] == "healthy":
                health_data["status"] = "degraded"
            health_data["warnings"] = health_data.get("warnings", [])
            health_data["warnings"].append(f"Warning: Low elevation file count: {len(elevation_files)}")
    else:
        health_data["elevation_files_available"] = 0
        health_data["status"] = "critical"
        health_data["errors"] = health_data.get("errors", [])
        health_data["errors"].append(f"Critical: Elevation data directory missing: {ELEVATION_DATA_DIR}")
    
    # Check map data availability with validation
    from config import PROJECT_ROOT
    mbtiles_file = PROJECT_ROOT / "output" / "usa-complete.mbtiles"
    
    if mbtiles_file.exists():
        size_gb = mbtiles_file.stat().st_size / (1024**3)
        health_data["map_tiles_available"] = 1
        health_data["mbtiles_size_gb"] = round(size_gb, 2)
        
        if size_gb < 1.0:
            health_data["status"] = "critical"
            health_data["errors"] = health_data.get("errors", [])
            health_data["errors"].append(f"Critical: MBTiles file too small: {size_gb:.1f}GB (expected ~1.6GB)")
    else:
        health_data["map_tiles_available"] = 0
        health_data["mbtiles_size_gb"] = 0
        health_data["status"] = "critical"
        health_data["errors"] = health_data.get("errors", [])
        health_data["errors"].append(f"Critical: MBTiles file missing: {mbtiles_file}")
    
    # Add deployment context
    health_data["deployment_context"] = {
        "project_root": str(PROJECT_ROOT),
        "elevation_data_dir": str(ELEVATION_DATA_DIR),
        "environment": os.getenv("ENVIRONMENT", "unknown")
    }
    
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
    """Get current memory usage in MB from /proc/self/status."""
    try:
        with open('/proc/self/status', 'r') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    # Extract memory in kB, convert to MB
                    memory_kb = int(line.split()[1])
                    return memory_kb / 1024
    except (FileNotFoundError, ValueError, IndexError):
        pass
    return 0.0

def _get_disk_usage() -> dict:
    """Get disk usage for key directories."""
    usage = {}
    
    key_dirs = HEALTH_CHECK_DIRS
    
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
    """Get system load information from /proc."""
    load_info = {}
    
    # Get load average
    try:
        with open('/proc/loadavg', 'r') as f:
            load_avg = f.read().strip().split()
            load_info["load_1m"] = float(load_avg[0])
    except (FileNotFoundError, ValueError, IndexError):
        pass
        
    # Get memory info
    try:
        with open('/proc/meminfo', 'r') as f:
            meminfo = {}
            for line in f:
                if ':' in line:
                    key, value = line.split(':', 1)
                    meminfo[key.strip()] = value.strip()
            
            total_kb = int(meminfo['MemTotal'].split()[0])
            available_kb = int(meminfo['MemAvailable'].split()[0])
            used_percent = ((total_kb - available_kb) / total_kb) * 100
            load_info["memory_percent"] = round(used_percent, 1)
    except (FileNotFoundError, ValueError, KeyError, IndexError):
        pass
        
    return load_info