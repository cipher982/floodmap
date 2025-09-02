"""
Performance testing endpoints for tile serving A/B tests.

Implements 4 variants for comparing different tile serving strategies:
1. runtime: Current production (runtime compression)  
2. precompressed: Pre-compressed files served via sendfile()
3. memory-cache: LRU cache of compressed tiles in RAM
4. uncompressed: Raw data, rely on CDN compression

Based on FloodMap Tile Serving Optimization PRD.
"""

from fastapi import APIRouter, HTTPException, Response, Path, Request
from fastapi.responses import FileResponse
import os
import time
import logging
import asyncio
import numpy as np
from pathlib import Path as PathLib
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from cachetools import LRUCache
import gzip

try:
    import brotli
except ImportError:
    brotli = None

# Import from existing modules
from elevation_loader import elevation_loader
from config import (
    TILE_SIZE, NODATA_VALUE, MIN_ZOOM, MAX_ZOOM,
    PROJECT_ROOT, IS_DEVELOPMENT
)
from .tiles_v1 import (
    validate_tile_coordinates, _negotiate_compression, 
    _maybe_compress, create_tile_response
)

router = APIRouter(prefix="/api/test", tags=["performance-testing"])
logger = logging.getLogger(__name__)

# Performance testing configuration
PERFORMANCE_TEST_DATA_DIR = PROJECT_ROOT / "tools" / "performance_testing" / "precompressed_tiles"
CACHE_TTL = 300 if IS_DEVELOPMENT else 31536000  # 5 min dev, 1 year prod

# Thread pool for CPU-intensive operations
CPU_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="perf-test")

# Memory cache for compressed tiles (variant 3)
# Size in number of tiles - each tile ~131KB + compressed variants ~20-90KB
MEMORY_CACHE_SIZE = 1000
memory_cache: LRUCache[str, bytes] = LRUCache(maxsize=MEMORY_CACHE_SIZE)

# Performance metrics collection
performance_metrics: Dict[str, list] = {
    "runtime": [],
    "precompressed": [],
    "memory_cache": [],
    "uncompressed": []
}


def record_performance_metric(variant: str, latency_ms: float, size_bytes: int, 
                            compression_ratio: Optional[float] = None):
    """Record performance metrics for analysis."""
    metric = {
        "timestamp": time.time(),
        "latency_ms": latency_ms,
        "size_bytes": size_bytes,
        "compression_ratio": compression_ratio
    }
    performance_metrics[variant].append(metric)
    
    # Keep only last 1000 metrics per variant to avoid memory bloat
    if len(performance_metrics[variant]) > 1000:
        performance_metrics[variant] = performance_metrics[variant][-1000:]


def generate_elevation_data_sync(z: int, x: int, y: int) -> bytes:
    """Generate raw elevation data - identical to production logic."""
    try:
        elevation_data = elevation_loader.get_elevation_for_tile(x, y, z, tile_size=TILE_SIZE)
        
        if elevation_data is None:
            empty_data = np.full((TILE_SIZE, TILE_SIZE), 65535, dtype=np.uint16)
            return empty_data.tobytes()
        
        # Convert elevation to uint16 format (same as production)
        normalized = np.zeros_like(elevation_data, dtype=np.float32)
        
        nodata_mask = (elevation_data == NODATA_VALUE) | (elevation_data < -500) | (elevation_data > 9000)
        valid_mask = ~nodata_mask
        
        normalized[valid_mask] = np.clip(
            (elevation_data[valid_mask] + 500) / 9500 * 65534, 0, 65534
        )
        normalized[nodata_mask] = 65535
        
        uint16_data = normalized.astype(np.uint16)
        return uint16_data.tobytes()
        
    except Exception as e:
        logger.error(f"Error generating elevation data for {z}/{x}/{y}: {e}")
        empty_data = np.full((TILE_SIZE, TILE_SIZE), 65535, dtype=np.uint16)
        return empty_data.tobytes()


# =============================================================================
# VARIANT 1: RUNTIME COMPRESSION (Current Production Baseline)
# =============================================================================

@router.get("/runtime/{z}/{x}/{y}.u16")
async def get_runtime_compressed_tile(
    z: int = Path(..., description="Zoom level"),
    x: int = Path(..., description="Tile X coordinate"),
    y: int = Path(..., description="Tile Y coordinate"),
    request: Request = None,
):
    """
    Variant 1: Runtime compression (current production baseline).
    Decompresses .zst → compresses to Brotli/Gzip per request.
    """
    start_time = time.time()
    validate_tile_coordinates(z, x, y)
    
    try:
        # Generate data (same as production)
        loop = asyncio.get_event_loop()
        elevation_data = await loop.run_in_executor(
            CPU_EXECUTOR, generate_elevation_data_sync, z, x, y
        )
        
        # Apply runtime compression
        accept_enc = request.headers.get("accept-encoding", "") if request else ""
        payload, cenc = _maybe_compress(elevation_data, accept_enc, min_size=512)
        
        # Record metrics
        latency_ms = (time.time() - start_time) * 1000
        compression_ratio = len(payload) / len(elevation_data) if len(elevation_data) > 0 else 1.0
        record_performance_metric("runtime", latency_ms, len(payload), compression_ratio)
        
        headers = {
            "Cache-Control": f"public, max-age={CACHE_TTL}",
            "Access-Control-Allow-Origin": "*",
            "X-Tile-Source": "performance-test-runtime",
            "X-Performance-Variant": "runtime",
            "X-Latency-Ms": str(round(latency_ms, 2)),
            "X-Compression-Ratio": str(round(compression_ratio, 3)),
        }
        if cenc:
            headers["Content-Encoding"] = cenc
            headers["Vary"] = "Accept-Encoding"
            
        return Response(
            content=payload,
            media_type="application/octet-stream",
            headers=headers
        )
        
    except Exception as e:
        logger.error(f"Runtime compression error for {z}/{x}/{y}: {e}")
        raise HTTPException(status_code=500, detail="Runtime compression failed")


# =============================================================================
# VARIANT 2: PRE-COMPRESSED FILES (Zero CPU)
# =============================================================================

@router.get("/precompressed/{z}/{x}/{y}.u16")
async def get_precompressed_tile(
    z: int = Path(..., description="Zoom level"),
    x: int = Path(..., description="Tile X coordinate"),
    y: int = Path(..., description="Tile Y coordinate"),
    request: Request = None,
):
    """
    Variant 2: Pre-compressed files served via sendfile().
    Zero CPU overhead, maximum I/O efficiency.
    """
    start_time = time.time()
    validate_tile_coordinates(z, x, y)
    
    try:
        # Determine preferred encoding
        accept_enc = request.headers.get("accept-encoding", "") if request else ""
        encoding = _negotiate_compression(accept_enc)
        
        # Look for pre-compressed file
        tile_dir = PERFORMANCE_TEST_DATA_DIR / str(z) / str(x)
        
        if encoding == 'br' and brotli:
            compressed_path = tile_dir / f"{y}.u16.br"
            if compressed_path.exists():
                latency_ms = (time.time() - start_time) * 1000
                
                # Get file sizes for metrics
                raw_path = tile_dir / f"{y}.u16"
                raw_size = raw_path.stat().st_size if raw_path.exists() else 131072
                compressed_size = compressed_path.stat().st_size
                compression_ratio = compressed_size / raw_size
                
                record_performance_metric("precompressed", latency_ms, compressed_size, compression_ratio)
                
                # Use FastAPI FileResponse for efficient sendfile()
                headers = {
                    "Content-Encoding": "br",
                    "Vary": "Accept-Encoding",
                    "Cache-Control": f"public, max-age={CACHE_TTL}",
                    "Access-Control-Allow-Origin": "*",
                    "X-Tile-Source": "performance-test-precompressed",
                    "X-Performance-Variant": "precompressed",
                    "X-Latency-Ms": str(round(latency_ms, 2)),
                    "X-Compression-Ratio": str(round(compression_ratio, 3)),
                }
                return FileResponse(
                    path=str(compressed_path),
                    media_type="application/octet-stream",
                    headers=headers
                )
        
        if encoding == 'gzip':
            compressed_path = tile_dir / f"{y}.u16.gz"
            if compressed_path.exists():
                latency_ms = (time.time() - start_time) * 1000
                
                raw_path = tile_dir / f"{y}.u16"
                raw_size = raw_path.stat().st_size if raw_path.exists() else 131072
                compressed_size = compressed_path.stat().st_size
                compression_ratio = compressed_size / raw_size
                
                record_performance_metric("precompressed", latency_ms, compressed_size, compression_ratio)
                
                headers = {
                    "Content-Encoding": "gzip",
                    "Vary": "Accept-Encoding", 
                    "Cache-Control": f"public, max-age={CACHE_TTL}",
                    "Access-Control-Allow-Origin": "*",
                    "X-Tile-Source": "performance-test-precompressed",
                    "X-Performance-Variant": "precompressed",
                    "X-Latency-Ms": str(round(latency_ms, 2)),
                    "X-Compression-Ratio": str(round(compression_ratio, 3)),
                }
                return FileResponse(
                    path=str(compressed_path),
                    media_type="application/octet-stream",
                    headers=headers
                )
        
        # Fallback to uncompressed if no compressed variant exists
        raw_path = tile_dir / f"{y}.u16"
        if raw_path.exists():
            latency_ms = (time.time() - start_time) * 1000
            file_size = raw_path.stat().st_size
            
            record_performance_metric("precompressed", latency_ms, file_size, 1.0)
            
            headers = {
                "Cache-Control": f"public, max-age={CACHE_TTL}",
                "Access-Control-Allow-Origin": "*",
                "X-Tile-Source": "performance-test-precompressed",
                "X-Performance-Variant": "precompressed",
                "X-Latency-Ms": str(round(latency_ms, 2)),
                "X-Compression-Ratio": "1.0",
            }
            return FileResponse(
                path=str(raw_path),
                media_type="application/octet-stream",
                headers=headers
            )
            
        # If no pre-compressed file exists, fall back to runtime generation
        logger.warning(f"No precompressed tile found for {z}/{x}/{y}, falling back to runtime")
        return await get_runtime_compressed_tile(z, x, y, request)
        
    except Exception as e:
        logger.error(f"Precompressed tile error for {z}/{x}/{y}: {e}")
        raise HTTPException(status_code=500, detail="Precompressed tile serving failed")


# =============================================================================
# VARIANT 3: MEMORY CACHE (Amortized CPU Cost)
# =============================================================================

@router.get("/memory-cache/{z}/{x}/{y}.u16")
async def get_memory_cached_tile(
    z: int = Path(..., description="Zoom level"),
    x: int = Path(..., description="Tile X coordinate"),
    y: int = Path(..., description="Tile Y coordinate"),
    request: Request = None,
):
    """
    Variant 3: Memory-cached compression.
    Compress once per tile, cache in RAM. Falls back to runtime for cache misses.
    """
    start_time = time.time()
    validate_tile_coordinates(z, x, y)
    
    try:
        # Determine preferred encoding
        accept_enc = request.headers.get("accept-encoding", "") if request else ""
        encoding = _negotiate_compression(accept_enc)
        
        # Create cache keys for different encodings
        cache_key_br = f"{z}/{x}/{y}.u16.br"
        cache_key_gz = f"{z}/{x}/{y}.u16.gz"
        cache_key_raw = f"{z}/{x}/{y}.u16.raw"
        
        # Check cache for preferred encoding
        cached_data = None
        cache_encoding = None
        compression_ratio = 1.0
        
        if encoding == 'br' and brotli and cache_key_br in memory_cache:
            cached_data = memory_cache[cache_key_br]
            cache_encoding = 'br'
        elif encoding == 'gzip' and cache_key_gz in memory_cache:
            cached_data = memory_cache[cache_key_gz] 
            cache_encoding = 'gzip'
        elif cache_key_raw in memory_cache:
            cached_data = memory_cache[cache_key_raw]
            cache_encoding = None
        
        # Cache hit - return immediately
        if cached_data is not None:
            latency_ms = (time.time() - start_time) * 1000
            
            # Estimate compression ratio from cached data size
            if cache_encoding:
                compression_ratio = len(cached_data) / 131072  # Assuming 131KB raw
                
            record_performance_metric("memory_cache", latency_ms, len(cached_data), compression_ratio)
            
            headers = {
                "Cache-Control": f"public, max-age={CACHE_TTL}",
                "Access-Control-Allow-Origin": "*", 
                "X-Tile-Source": "performance-test-memory-cache",
                "X-Performance-Variant": "memory-cache",
                "X-Cache-Status": "HIT",
                "X-Latency-Ms": str(round(latency_ms, 2)),
                "X-Compression-Ratio": str(round(compression_ratio, 3)),
            }
            if cache_encoding:
                headers["Content-Encoding"] = cache_encoding
                headers["Vary"] = "Accept-Encoding"
                
            return Response(
                content=cached_data,
                media_type="application/octet-stream",
                headers=headers
            )
        
        # Cache miss - generate and cache
        loop = asyncio.get_event_loop()
        elevation_data = await loop.run_in_executor(
            CPU_EXECUTOR, generate_elevation_data_sync, z, x, y
        )
        
        # Store raw data in cache
        memory_cache[cache_key_raw] = elevation_data
        
        # Generate and cache compressed variants
        payload = elevation_data
        response_encoding = None
        
        if encoding == 'br' and brotli:
            try:
                compressed_br = brotli.compress(elevation_data, quality=1)
                memory_cache[cache_key_br] = compressed_br
                payload = compressed_br
                response_encoding = 'br'
                compression_ratio = len(compressed_br) / len(elevation_data)
            except Exception:
                pass
                
        elif encoding == 'gzip':
            try:
                compressed_gz = gzip.compress(elevation_data, compresslevel=1)
                memory_cache[cache_key_gz] = compressed_gz
                payload = compressed_gz
                response_encoding = 'gzip'
                compression_ratio = len(compressed_gz) / len(elevation_data)
            except Exception:
                pass
        
        latency_ms = (time.time() - start_time) * 1000
        record_performance_metric("memory_cache", latency_ms, len(payload), compression_ratio)
        
        headers = {
            "Cache-Control": f"public, max-age={CACHE_TTL}",
            "Access-Control-Allow-Origin": "*",
            "X-Tile-Source": "performance-test-memory-cache", 
            "X-Performance-Variant": "memory-cache",
            "X-Cache-Status": "MISS",
            "X-Latency-Ms": str(round(latency_ms, 2)),
            "X-Compression-Ratio": str(round(compression_ratio, 3)),
        }
        if response_encoding:
            headers["Content-Encoding"] = response_encoding
            headers["Vary"] = "Accept-Encoding"
            
        return Response(
            content=payload,
            media_type="application/octet-stream", 
            headers=headers
        )
        
    except Exception as e:
        logger.error(f"Memory cache error for {z}/{x}/{y}: {e}")
        raise HTTPException(status_code=500, detail="Memory cache tile serving failed")


# =============================================================================
# VARIANT 4: UNCOMPRESSED (CDN Reliance)
# =============================================================================

@router.get("/uncompressed/{z}/{x}/{y}.u16")
async def get_uncompressed_tile(
    z: int = Path(..., description="Zoom level"),
    x: int = Path(..., description="Tile X coordinate"),
    y: int = Path(..., description="Tile Y coordinate"),
    request: Request = None,
):
    """
    Variant 4: Uncompressed raw data.
    Relies on CDN/CloudFlare edge compression. Zero origin CPU overhead.
    """
    start_time = time.time()
    validate_tile_coordinates(z, x, y)
    
    try:
        # Generate raw data without any compression
        loop = asyncio.get_event_loop()
        elevation_data = await loop.run_in_executor(
            CPU_EXECUTOR, generate_elevation_data_sync, z, x, y
        )
        
        latency_ms = (time.time() - start_time) * 1000
        record_performance_metric("uncompressed", latency_ms, len(elevation_data), 1.0)
        
        headers = {
            "Cache-Control": f"public, max-age={CACHE_TTL}",
            "Access-Control-Allow-Origin": "*",
            "X-Tile-Source": "performance-test-uncompressed",
            "X-Performance-Variant": "uncompressed", 
            "X-Latency-Ms": str(round(latency_ms, 2)),
            "X-Compression-Ratio": "1.0",
            # Allow CDN to apply compression
            "Vary": "Accept-Encoding",
        }
        
        return Response(
            content=elevation_data,
            media_type="application/octet-stream",
            headers=headers
        )
        
    except Exception as e:
        logger.error(f"Uncompressed tile error for {z}/{x}/{y}: {e}")
        raise HTTPException(status_code=500, detail="Uncompressed tile serving failed")


# =============================================================================
# PERFORMANCE METRICS & DIAGNOSTICS
# =============================================================================

@router.get("/metrics")
async def get_performance_metrics():
    """Get collected performance metrics for all variants."""
    
    def calculate_stats(metrics_list):
        if not metrics_list:
            return {"count": 0}
            
        latencies = [m["latency_ms"] for m in metrics_list]
        sizes = [m["size_bytes"] for m in metrics_list]
        ratios = [m["compression_ratio"] for m in metrics_list if m["compression_ratio"]]
        
        return {
            "count": len(metrics_list),
            "latency_ms": {
                "min": min(latencies),
                "max": max(latencies),
                "avg": sum(latencies) / len(latencies),
                "p95": sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) >= 20 else None
            },
            "size_bytes": {
                "min": min(sizes),
                "max": max(sizes),
                "avg": sum(sizes) / len(sizes)
            },
            "compression_ratio": {
                "min": min(ratios) if ratios else None,
                "max": max(ratios) if ratios else None,
                "avg": sum(ratios) / len(ratios) if ratios else None
            }
        }
    
    return {
        "cache_stats": {
            "memory_cache_size": len(memory_cache),
            "memory_cache_maxsize": memory_cache.maxsize
        },
        "variants": {
            variant: calculate_stats(metrics)
            for variant, metrics in performance_metrics.items()
        }
    }


@router.get("/health")
async def performance_test_health():
    """Health check for performance testing endpoints."""
    
    # Check if pre-compressed tiles directory exists
    precompressed_available = PERFORMANCE_TEST_DATA_DIR.exists()
    
    # Count available pre-compressed tiles
    tile_count = 0
    if precompressed_available:
        try:
            manifest_path = PERFORMANCE_TEST_DATA_DIR / "manifest.json"
            if manifest_path.exists():
                import json
                with open(manifest_path) as f:
                    manifest = json.load(f)
                    tile_count = manifest.get("tile_count", 0)
        except Exception:
            pass
    
    return {
        "status": "healthy",
        "variants": {
            "runtime": "available",
            "precompressed": "available" if precompressed_available else "no_data", 
            "memory_cache": "available",
            "uncompressed": "available"
        },
        "precompressed_tiles_count": tile_count,
        "memory_cache_size": len(memory_cache),
        "endpoints": {
            "runtime": "/api/test/runtime/{z}/{x}/{y}.u16",
            "precompressed": "/api/test/precompressed/{z}/{x}/{y}.u16", 
            "memory_cache": "/api/test/memory-cache/{z}/{x}/{y}.u16",
            "uncompressed": "/api/test/uncompressed/{z}/{x}/{y}.u16"
        }
    }