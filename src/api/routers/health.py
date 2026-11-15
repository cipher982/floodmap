"""Health check endpoints."""

import os
from datetime import datetime

from config import (
    ELEVATION_DATA_DIR,
    ENABLE_DIAGNOSTICS,
    ENVIRONMENT,
    HEALTH_CHECK_DIRS,
    IS_DEVELOPMENT,
    MAP_DATA_DIR,
    TERRAIN_MANIFEST_PATH,
    TERRAIN_REMOTE_BASE_URL,
    TERRAIN_V2_ENABLED,
)
from fastapi import APIRouter, HTTPException

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
ops_router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint without internal filesystem or telemetry details."""
    health_data: dict = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "flood-map-api",
        "version": "2.0.0",
    }

    if HEALTH_MONITORING and not health_monitor.is_healthy():
        health_data["status"] = "unhealthy"

    terrain_remote_enabled = bool(TERRAIN_REMOTE_BASE_URL)
    terrain_manifest_available = (
        TERRAIN_V2_ENABLED and TERRAIN_MANIFEST_PATH.exists()
    ) or terrain_remote_enabled
    health_data["terrain_v2_enabled"] = TERRAIN_V2_ENABLED or terrain_remote_enabled
    health_data["terrain_manifest_available"] = terrain_manifest_available
    if terrain_remote_enabled:
        health_data["terrain_remote_enabled"] = True

    # Check legacy elevation source availability without exposing filesystem paths.
    if ELEVATION_DATA_DIR.exists():
        elevation_files = list(ELEVATION_DATA_DIR.glob("*.zst"))
        if len(elevation_files) < 1000:
            if terrain_manifest_available:
                health_data.setdefault("warnings", []).append(
                    "Legacy elevation source inventory is missing; terrain v2 manifest is available."
                )
            else:
                health_data["status"] = "critical"
                health_data.setdefault("errors", []).append(
                    "Critical: Insufficient legacy elevation source tiles."
                )
        elif len(elevation_files) < 2000:
            if health_data["status"] == "healthy":
                health_data["status"] = "degraded"
            health_data.setdefault("warnings", []).append(
                "Warning: Low legacy elevation source count."
            )
    else:
        if terrain_manifest_available:
            health_data.setdefault("warnings", []).append(
                "Legacy elevation source directory is missing; terrain v2 manifest is available."
            )
        else:
            health_data["status"] = "critical"
            health_data.setdefault("errors", []).append(
                "Critical: Elevation data directory missing."
            )

    # Check map data availability without exposing filesystem paths or file sizes.
    mbtiles_file = MAP_DATA_DIR / "usa-complete.mbtiles"
    if mbtiles_file.exists():
        size_gb = mbtiles_file.stat().st_size / (1024**3)
        if size_gb < 1.0:
            health_data["status"] = "critical"
            health_data.setdefault("errors", []).append(
                "Critical: Base map dataset is incomplete."
            )
    else:
        health_data["status"] = "critical"
        health_data.setdefault("errors", []).append(
            "Critical: Base map dataset missing."
        )

    if IS_DEVELOPMENT:
        health_data["deployment_context"] = {"environment": ENVIRONMENT}

    return health_data


@ops_router.get("/metrics")
async def get_metrics():
    """Get detailed system metrics (development/diagnostics only)."""
    if not (IS_DEVELOPMENT or ENABLE_DIAGNOSTICS):
        raise HTTPException(status_code=404, detail="Not found")
    stats = {}

    if HEALTH_MONITORING:
        stats.update(health_monitor.get_stats())

    # Add system information
    stats.update(
        {
            "memory_usage_mb": _get_memory_usage(),
            "disk_usage": _get_disk_usage(),
            "system_load": _get_system_load(),
        }
    )

    # Add cache statistics
    if CACHE_STATS:
        stats["cache"] = tile_cache.stats()

    # Add multi-core system statistics
    if MULTICORE_STATS:
        stats["elevation_cache"] = persistent_elevation_cache.get_stats()
        stats["predictive_preloader"] = predictive_preloader.get_stats()

    return stats


@ops_router.get("/cache")
async def get_cache_stats():
    """Get tile cache statistics (development/diagnostics only)."""
    if not (IS_DEVELOPMENT or ENABLE_DIAGNOSTICS):
        raise HTTPException(status_code=404, detail="Not found")
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
        "timestamp": datetime.utcnow().isoformat(),
    }


def _get_memory_usage() -> float:
    """Get current memory usage in MB from /proc/self/status."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
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
                    "free_gb": free / (1024**3),
                }
            except Exception:
                pass

    return usage


def _get_system_load() -> dict:
    """Get system load information from /proc."""
    load_info = {}

    # Get load average
    try:
        with open("/proc/loadavg") as f:
            load_avg = f.read().strip().split()
            load_info["load_1m"] = float(load_avg[0])
    except (FileNotFoundError, ValueError, IndexError):
        pass

    # Get memory info
    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                if ":" in line:
                    key, value = line.split(":", 1)
                    meminfo[key.strip()] = value.strip()

            total_kb = int(meminfo["MemTotal"].split()[0])
            available_kb = int(meminfo["MemAvailable"].split()[0])
            used_percent = ((total_kb - available_kb) / total_kb) * 100
            load_info["memory_percent"] = round(used_percent, 1)
    except (FileNotFoundError, ValueError, KeyError, IndexError):
        pass

    return load_info
