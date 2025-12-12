"""
Clean v1 tile serving API - consistent, RESTful, and well-designed.
Implements the route redesign PRD with proper error handling and caching.
"""

import asyncio
import gzip
import io
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

import httpx
import numpy as np
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from fastapi.responses import Response

try:
    import brotli  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    brotli = None

# Load environment variables
load_dotenv()

from color_mapping import color_mapper
from config import (
    MAX_WATER_LEVEL,
    MAX_ZOOM,
    MIN_WATER_LEVEL,
    MIN_ZOOM,
    NODATA_VALUE,
    PRECOMPRESSED_TILES_DIR,
    TILE_CACHE_CONTROL,
    TILE_CACHE_MAX_AGE,
    TILE_SIZE,
    TILESERVER_URL,
    VECTOR_TILE_MIN_SIZE,
)
from elevation_loader import elevation_loader  # Uses preprocessed aligned data
from error_handling import log_performance, safe_tile_generation
from persistent_elevation_cache import persistent_elevation_cache
from predictive_preloader import predictive_preloader
from tile_cache import tile_cache

router = APIRouter(prefix="/api/v1/tiles", tags=["tiles-v1"])
logger = logging.getLogger(__name__)

# Thread pool for CPU-intensive tile generation
CPU_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tile-cpu-v1")

# Constants
SUPPORTED_ZOOM_RANGE = (MIN_ZOOM, MAX_ZOOM)
SUPPORTED_WATER_LEVEL_RANGE = (MIN_WATER_LEVEL, MAX_WATER_LEVEL)

# Pre-generate constant NODATA tile for precompressed misses
# This is a 256x256 uint16 array with all values set to 65535 (NODATA)
_NODATA_TILE_BYTES = np.full((TILE_SIZE, TILE_SIZE), 65535, dtype=np.uint16).tobytes()

# Pre-compress the NODATA tile at module load time for efficient serving
_NODATA_TILE_GZIP = gzip.compress(_NODATA_TILE_BYTES, compresslevel=1)
_NODATA_TILE_BROTLI = None
if brotli is not None:
    try:
        _NODATA_TILE_BROTLI = brotli.compress(_NODATA_TILE_BYTES, quality=1)
    except Exception:
        pass  # Fallback to gzip if brotli fails


def _negotiate_compression(accept_encoding: str) -> str | None:
    """Return preferred encoding ('br' or 'gzip') based on Accept-Encoding.
    Prefers brotli when available; falls back to gzip. Returns None for identity.
    """
    enc = accept_encoding.lower()
    if "br" in enc and brotli is not None:
        return "br"
    if "gzip" in enc:
        return "gzip"
    return None


def _maybe_compress(
    content: bytes, accept_encoding: str, min_size: int = 1024
) -> tuple[bytes, str | None]:
    """Compress content if client supports it and payload exceeds min_size.

    Returns (payload_bytes, content_encoding or None)
    """
    if len(content) < min_size:
        return content, None
    encoding = _negotiate_compression(accept_encoding)
    if encoding == "br":
        # brotli level 1 for speed over compression ratio
        try:
            return brotli.compress(content, quality=1), "br"  # type: ignore[arg-type]
        except Exception:
            return content, None
    if encoding == "gzip":
        try:
            return gzip.compress(content, compresslevel=1), "gzip"
        except Exception:
            return content, None
    return content, None


def validate_tile_coordinates(z: int, x: int, y: int) -> None:
    """Validate tile coordinates according to TMS/XYZ standards."""
    if not (SUPPORTED_ZOOM_RANGE[0] <= z <= SUPPORTED_ZOOM_RANGE[1]):
        raise HTTPException(
            status_code=400,
            detail=f"Zoom level must be between {SUPPORTED_ZOOM_RANGE[0]} and {SUPPORTED_ZOOM_RANGE[1]}",
        )

    max_coord = 2**z
    if not (0 <= x < max_coord):
        raise HTTPException(
            status_code=400,
            detail=f"X coordinate must be between 0 and {max_coord - 1} for zoom level {z}",
        )

    if not (0 <= y < max_coord):
        raise HTTPException(
            status_code=400,
            detail=f"Y coordinate must be between 0 and {max_coord - 1} for zoom level {z}",
        )


def validate_water_level(water_level: float) -> None:
    """Validate water level parameter."""
    if not (
        SUPPORTED_WATER_LEVEL_RANGE[0] <= water_level <= SUPPORTED_WATER_LEVEL_RANGE[1]
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Water level must be between {SUPPORTED_WATER_LEVEL_RANGE[0]} and {SUPPORTED_WATER_LEVEL_RANGE[1]} meters",
        )


def create_tile_response(
    content: bytes,
    content_type: str,
    tile_source: str,
    water_level: float = None,
    cache_status: str = "MISS",
) -> Response:
    """Create standardized tile response with proper headers."""
    headers = {
        "Cache-Control": TILE_CACHE_CONTROL,
        "X-Tile-Source": tile_source,
        "X-Cache": cache_status,
        "Access-Control-Allow-Origin": "*",
        # Always vary on Accept-Encoding as payload may differ
        "Vary": "Accept-Encoding",
    }

    if water_level is not None:
        headers["X-Water-Level"] = str(water_level)

    return Response(content=content, media_type=content_type, headers=headers)


def get_transparent_tile_bytes() -> bytes:
    """Return minimal transparent PNG as bytes."""
    return b"\\x89PNG\\r\\n\\x1a\\n\\x00\\x00\\x00\\rIHDR\\x00\\x00\\x01\\x00\\x00\\x00\\x01\\x00\\x08\\x06\\x00\\x00\\x00\\x1f\\x15\\xc4\\x89\\x00\\x00\\x00\\rIDATx\\x9cc\\xf8\\x0f\\x00\\x00\\x01\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x07:\\xb9Y\\x00\\x00\\x00\\x00IEND\\xaeB`\\x82"


# ============================================================================
# VECTOR TILES (Base Maps)
# ============================================================================


@router.get("/vector/{source}/{z}/{x}/{y}.pbf")
async def get_vector_tile(
    source: Literal["usa"] = Path(..., description="Vector tile source"),
    z: int = Path(..., description="Zoom level", ge=0, le=18),
    x: int = Path(..., description="Tile X coordinate"),
    y: int = Path(..., description="Tile Y coordinate"),
    request: Request = None,
):
    """
    Serve vector tiles (base maps) from tileserver.

    Sources:
    - usa: USA-wide vector tiles from usa-complete dataset
    """
    # Validate coordinates for vector tiles (broader zoom range)
    if not (0 <= z <= 18):
        raise HTTPException(
            status_code=400, detail="Vector tile zoom level must be between 0 and 18"
        )

    max_coord = 2**z
    if not (0 <= x < max_coord and 0 <= y < max_coord):
        raise HTTPException(
            status_code=400, detail="Invalid tile coordinates for zoom level"
        )

    # Map source names to tileserver sources
    source_mapping = {"usa": "usa-complete"}

    tileserver_source = source_mapping.get(source)
    if not tileserver_source:
        raise HTTPException(
            status_code=400, detail=f"Unsupported vector source: {source}"
        )

    # Use simple httpx with correct port configuration
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Request identity encoding from upstream; compress for client below
            response = await client.get(
                f"{TILESERVER_URL}/data/{tileserver_source}/{z}/{x}/{y}.pbf",
                headers={"Accept-Encoding": "identity"},
            )

            if response.status_code == 200:
                content = response.content
                # Compress for client if supported
                accept_enc = (
                    request.headers.get("accept-encoding", "") if request else ""
                )
                payload, cenc = _maybe_compress(
                    content, accept_enc, min_size=VECTOR_TILE_MIN_SIZE
                )
                resp = create_tile_response(
                    content=payload,
                    content_type="application/x-protobuf",
                    tile_source="vector",
                )
                if cenc:
                    resp.headers["Content-Encoding"] = cenc
                    resp.headers["Vary"] = "Accept-Encoding"
                return resp
            elif response.status_code == 204:
                return create_tile_response(
                    content=b"",
                    content_type="application/x-protobuf",
                    tile_source="vector",
                )
            else:
                raise HTTPException(status_code=404, detail="Vector tile not found")
        except httpx.RequestError as e:
            logger.error(f"Tileserver connection error: {e}")
            raise HTTPException(
                status_code=503, detail="Vector tile service unavailable"
            )


# ============================================================================
# ELEVATION TILES (Raw Elevation)
# ============================================================================


def generate_elevation_tile_sync(z: int, x: int, y: int) -> bytes:
    """Generate raw elevation tile (no water level) synchronously."""
    try:
        # Get tile bounds for elevation file lookup
        lat_top, lat_bottom, lon_left, lon_right = elevation_loader.num2deg(x, y, z)

        # Find elevation files using O(1) lookup
        overlapping_files = elevation_loader.find_elevation_files_for_tile(
            lat_top, lat_bottom, lon_left, lon_right
        )

        if not overlapping_files:
            logger.error(f"No elevation files found for tile {z}/{x}/{y}")
            raise HTTPException(
                status_code=503,
                detail="Elevation data not available. Run 'make process-elevation' to generate required data files.",
            )

        # OPTIMIZED: Get elevation data from persistent cache with direct extraction
        elevation_data = None
        for file_path in overlapping_files:
            # Use optimized cached extraction - no zstd decompression!
            elevation_data = persistent_elevation_cache.extract_tile_from_cached_array(
                file_path, lat_top, lat_bottom, lon_left, lon_right, TILE_SIZE
            )
            if elevation_data is not None:
                break

        if elevation_data is None:
            logger.error(f"No elevation data could be extracted for tile {z}/{x}/{y}")
            raise HTTPException(
                status_code=503,
                detail="Elevation data extraction failed. Run 'make process-elevation' to generate required data files.",
            )

        # Convert elevation to grayscale visualization (no water level)
        # Use elevation values directly for visualization
        normalized_elevation = (
            ((elevation_data + 500) / 4000 * 255).clip(0, 255).astype("uint8")
        )

        # Create grayscale image
        from PIL import Image

        img = Image.fromarray(normalized_elevation, "L").convert("RGBA")

        # Convert to PNG bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG", optimize=True, compress_level=1)
        img_bytes.seek(0)

        return img_bytes.getvalue()

    except Exception as e:
        logger.error(f"Error generating elevation tile {z}/{x}/{y}: {e}")
        return get_transparent_tile_bytes()


@router.get("/elevation/{z}/{x}/{y}.png")
@log_performance
async def get_elevation_tile(
    z: int = Path(..., description="Zoom level"),
    x: int = Path(..., description="Tile X coordinate"),
    y: int = Path(..., description="Tile Y coordinate"),
):
    """
    Serve raw elevation tiles (no water level applied).
    Returns grayscale elevation visualization.
    """
    validate_tile_coordinates(z, x, y)

    try:
        # Check cache first (using special cache key for raw elevation)
        cache_key_water_level = -999.0  # Special value for raw elevation
        cached_tile = tile_cache.get(cache_key_water_level, z, x, y)
        if cached_tile is not None:
            return create_tile_response(
                content=cached_tile,
                content_type="image/png",
                tile_source="elevation",
                cache_status="HIT",
            )

        # Generate tile asynchronously
        loop = asyncio.get_event_loop()
        tile_data = await loop.run_in_executor(
            CPU_EXECUTOR, generate_elevation_tile_sync, z, x, y
        )

        # Cache the generated tile
        tile_cache.put(cache_key_water_level, z, x, y, tile_data)

        # Return empty response if no elevation data
        if len(tile_data) <= 100:  # Transparent tile is very small
            return Response(status_code=204)  # No Content

        return create_tile_response(
            content=tile_data,
            content_type="image/png",
            tile_source="elevation",
            cache_status="MISS",
        )

    except Exception as e:
        logger.error(f"Error serving elevation tile {z}/{x}/{y}: {e}")
        raise HTTPException(status_code=500, detail="Elevation tile generation failed")


# ============================================================================
# FLOOD OVERLAY TILES
# ============================================================================


def generate_flood_tile_sync(water_level: float, z: int, x: int, y: int) -> bytes:
    """Generate flood overlay tile synchronously."""
    try:
        # Get tile bounds for elevation file lookup
        lat_top, lat_bottom, lon_left, lon_right = elevation_loader.num2deg(x, y, z)

        # Find elevation files using O(1) lookup
        overlapping_files = elevation_loader.find_elevation_files_for_tile(
            lat_top, lat_bottom, lon_left, lon_right
        )

        if not overlapping_files:
            logger.error(
                f"No elevation files found for flood tile {water_level}m/{z}/{x}/{y}"
            )
            raise HTTPException(
                status_code=503,
                detail="Elevation data not available. Run 'make process-elevation' to generate required data files.",
            )

        # OPTIMIZED: Get elevation data from persistent cache with direct extraction
        elevation_data = None
        for file_path in overlapping_files:
            # Use optimized cached extraction - no zstd decompression!
            elevation_data = persistent_elevation_cache.extract_tile_from_cached_array(
                file_path, lat_top, lat_bottom, lon_left, lon_right, TILE_SIZE
            )
            if elevation_data is not None:
                break

        if elevation_data is None:
            logger.error(
                f"No elevation data could be extracted for flood tile {water_level}m/{z}/{x}/{y}"
            )
            raise HTTPException(
                status_code=503,
                detail="Elevation data extraction failed. Run 'make process-elevation' to generate required data files.",
            )

        # Convert elevation to flood overlay using color mapper
        rgba_array = color_mapper.elevation_array_to_rgba(
            elevation_data, water_level, no_data_value=-32768
        )

        # Convert to PIL Image
        from PIL import Image

        img = Image.fromarray(rgba_array, "RGBA")

        # Convert to PNG bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG", optimize=True, compress_level=1)
        img_bytes.seek(0)

        return img_bytes.getvalue()

    except Exception as e:
        logger.error(f"Error generating flood tile {water_level}m/{z}/{x}/{y}: {e}")
        return get_transparent_tile_bytes()


@router.get("/flood/{water_level}/{z}/{x}/{y}.png")
@log_performance
async def get_flood_tile(
    water_level: float = Path(..., description="Water level in meters"),
    z: int = Path(..., description="Zoom level"),
    x: int = Path(..., description="Tile X coordinate"),
    y: int = Path(..., description="Tile Y coordinate"),
):
    """
    DEPRECATED: This endpoint should not be used with client-side rendering.
    The client should use /elevation-data/{z}/{x}/{y}.u16 instead.
    """
    raise HTTPException(
        status_code=501,
        detail="Server-side flood tiles are disabled. Use client-side rendering with /elevation-data/{z}/{x}/{y}.u16",
    )

    # OLD CODE DISABLED - Client should render tiles
    return
    validate_water_level(water_level)
    validate_tile_coordinates(z, x, y)

    try:
        # Check cache first
        cached_tile = tile_cache.get(water_level, z, x, y)
        if cached_tile is not None:
            return create_tile_response(
                content=cached_tile,
                content_type="image/png",
                tile_source="flood",
                water_level=water_level,
                cache_status="HIT",
            )

        # Record request for predictive preloading
        predictive_preloader.record_tile_request(z, x, y, water_level)

        # Generate tile asynchronously
        loop = asyncio.get_event_loop()
        tile_data = await loop.run_in_executor(
            CPU_EXECUTOR, generate_flood_tile_sync, water_level, z, x, y
        )

        # Cache the generated tile
        tile_cache.put(water_level, z, x, y, tile_data)

        # Return empty response if no flood data
        if len(tile_data) <= 100:  # Transparent tile is very small
            return Response(status_code=204)  # No Content

        return create_tile_response(
            content=tile_data,
            content_type="image/png",
            tile_source="flood",
            water_level=water_level,
            cache_status="MISS",
        )

    except Exception as e:
        logger.error(f"Error serving flood tile {water_level}m/{z}/{x}/{y}: {e}")
        raise HTTPException(status_code=500, detail="Flood tile generation failed")


# ============================================================================
# RAW ELEVATION DATA (Client-Side Rendering)
# ============================================================================


def generate_elevation_data_sync(z: int, x: int, y: int) -> bytes:
    """Generate raw elevation data as Uint16 array for client-side rendering."""
    try:
        # Get elevation data from preprocessed aligned file
        elevation_data = elevation_loader.get_elevation_for_tile(
            x, y, z, tile_size=TILE_SIZE
        )

        if elevation_data is None:
            # Return empty elevation data
            empty_data = np.full((TILE_SIZE, TILE_SIZE), 65535, dtype=np.uint16)
            return empty_data.tobytes()

        # Convert elevation to uint16 format
        # Range: -500m to 9000m → 0 to 65534
        # Special value: 65535 = NODATA
        normalized = np.zeros_like(elevation_data, dtype=np.float32)

        # Handle NODATA values
        nodata_mask = (
            (elevation_data == NODATA_VALUE)
            | (elevation_data < -500)
            | (elevation_data > 9000)
        )
        valid_mask = ~nodata_mask

        # Normalize valid elevations to 0-65534 range
        normalized[valid_mask] = np.clip(
            (elevation_data[valid_mask] + 500) / 9500 * 65534, 0, 65534
        )
        normalized[nodata_mask] = 65535

        # Convert to uint16
        uint16_data = normalized.astype(np.uint16)

        return uint16_data.tobytes()

    except Exception as e:
        logger.error(f"Error generating elevation data for {z}/{x}/{y}: {e}")
        # Return empty elevation data on error
        empty_data = np.full((TILE_SIZE, TILE_SIZE), 65535, dtype=np.uint16)
        return empty_data.tobytes()


async def serve_precompressed_elevation_tile(
    z: int, x: int, y: int, request: Request = None
):
    """Serve pre-compressed elevation tiles directly from disk via sendfile."""
    import time

    from fastapi.responses import FileResponse

    start_time = time.time()

    try:
        # Determine preferred encoding
        accept_enc = request.headers.get("accept-encoding", "") if request else ""
        encoding = _negotiate_compression(accept_enc)

        # Look for pre-compressed file in configured storage
        if PRECOMPRESSED_TILES_DIR is None:
            raise HTTPException(
                status_code=501, detail="Pre-compressed tiles not configured"
            )

        tile_dir = PRECOMPRESSED_TILES_DIR / str(z) / str(x)

        # Try compressed variants first
        if encoding == "br" and brotli:
            compressed_path = tile_dir / f"{y}.u16.br"
            if compressed_path.exists():
                latency_ms = (time.time() - start_time) * 1000
                file_size = compressed_path.stat().st_size
                logger.info(
                    f"TILE {z}/{x}/{y}: precompressed-br, {latency_ms:.1f}ms, {file_size:,}b"
                )
                headers = {
                    "Content-Encoding": "br",
                    "Vary": "Accept-Encoding",
                    "Cache-Control": TILE_CACHE_CONTROL,
                    "Access-Control-Allow-Origin": "*",
                    "X-Tile-Source": "precompressed-br",
                    "X-Method": "precompressed",
                    "X-Latency-Ms": str(round(latency_ms, 2)),
                }
                return FileResponse(
                    path=str(compressed_path),
                    media_type="application/octet-stream",
                    headers=headers,
                )

        if encoding == "gzip":
            compressed_path = tile_dir / f"{y}.u16.gz"
            if compressed_path.exists():
                latency_ms = (time.time() - start_time) * 1000
                file_size = compressed_path.stat().st_size
                logger.info(
                    f"TILE {z}/{x}/{y}: precompressed-gz, {latency_ms:.1f}ms, {file_size:,}b"
                )
                headers = {
                    "Content-Encoding": "gzip",
                    "Vary": "Accept-Encoding",
                    "Cache-Control": TILE_CACHE_CONTROL,
                    "Access-Control-Allow-Origin": "*",
                    "X-Tile-Source": "precompressed-gz",
                    "X-Method": "precompressed",
                    "X-Latency-Ms": str(round(latency_ms, 2)),
                }
                return FileResponse(
                    path=str(compressed_path),
                    media_type="application/octet-stream",
                    headers=headers,
                )

        # Fallback to uncompressed pre-generated file
        raw_path = tile_dir / f"{y}.u16"
        if raw_path.exists():
            latency_ms = (time.time() - start_time) * 1000
            file_size = raw_path.stat().st_size
            logger.info(
                f"TILE {z}/{x}/{y}: precompressed-raw, {latency_ms:.1f}ms, {file_size:,}b"
            )
            headers = {
                "Cache-Control": TILE_CACHE_CONTROL,
                "Access-Control-Allow-Origin": "*",
                "X-Tile-Source": "precompressed-raw",
                "X-Method": "precompressed",
                "X-Latency-Ms": str(round(latency_ms, 2)),
                # Ensure caches separate by Accept-Encoding even for identity
                "Vary": "Accept-Encoding",
            }
            return FileResponse(
                path=str(raw_path),
                media_type="application/octet-stream",
                headers=headers,
            )

        # If no pre-compressed files exist, return constant NODATA tile immediately
        # This avoids expensive runtime generation for ocean/missing tiles
        logger.info(
            f"No precompressed tile found for {z}/{x}/{y}, returning NODATA tile"
        )

        # Select appropriate pre-compressed NODATA tile based on client support
        if encoding == "br" and _NODATA_TILE_BROTLI is not None:
            payload = _NODATA_TILE_BROTLI
            content_encoding = "br"
        elif encoding == "gzip":
            payload = _NODATA_TILE_GZIP
            content_encoding = "gzip"
        else:
            payload = _NODATA_TILE_BYTES
            content_encoding = None

        latency_ms = (time.time() - start_time) * 1000
        compression_info = content_encoding if content_encoding else "uncompressed"
        logger.info(
            f"TILE {z}/{x}/{y}: nodata-{compression_info}, {latency_ms:.1f}ms, {len(payload):,}b"
        )

        headers = {
            "Cache-Control": "public, max-age=31536000, immutable",
            "Access-Control-Allow-Origin": "*",
            "X-Tile-Source": "nodata",
            "X-Method": "precompressed",
            "X-Precompressed-Miss": "1",
            "X-Latency-Ms": str(round(latency_ms, 2)),
            "Vary": "Accept-Encoding",
        }
        if content_encoding:
            headers["Content-Encoding"] = content_encoding

        return Response(
            content=payload, media_type="application/octet-stream", headers=headers
        )

    except Exception as e:
        logger.error(f"Precompressed tile error for {z}/{x}/{y}: {e}")
        raise HTTPException(status_code=500, detail="Precompressed tile serving failed")


@router.get("/elevation-data/{z}/{x}/{y}.u16")
@log_performance
async def get_elevation_data_tile(
    z: int = Path(..., description="Zoom level"),
    x: int = Path(..., description="Tile X coordinate"),
    y: int = Path(..., description="Tile Y coordinate"),
    method: str = Query(
        "runtime", description="Serving method: 'runtime' or 'precompressed'"
    ),
    request: Request = None,
):
    """
    Serve raw elevation data as Uint16 binary array for client-side rendering.

    Format:
    - 256x256 pixels as uint16 values (131,072 bytes uncompressed)
    - Values 0-65534: Elevation from -500m to 9000m
    - Value 65535: NODATA (ocean/missing data)
    - Cached forever (immutable elevation data)

    Method parameter:
    - runtime: Generate tiles with runtime compression (default, may fallback to runtime generation)
    - precompressed: Disk-only mode - serves precompressed files if they exist,
                     otherwise returns a constant NODATA tile immediately (no expensive generation).
                     Includes X-Precompressed-Miss header for debugging when NODATA fallback is used.
    """
    validate_tile_coordinates(z, x, y)

    # Route to pre-compressed serving if requested
    if method == "precompressed":
        if PRECOMPRESSED_TILES_DIR is None:
            raise HTTPException(
                status_code=501,
                detail="Pre-compressed tiles not configured (PRECOMPRESSED_TILES_DIR not set)",
            )
        return await serve_precompressed_elevation_tile(z, x, y, request)

    # Default runtime compression method
    try:
        start_time = time.time()
        # Check cache first (using special cache key for raw data)
        cache_key_format = -1000.0  # Special value for raw elevation data
        cached_data = tile_cache.get(cache_key_format, z, x, y)
        if cached_data is not None:
            # Negotiate compression per request (cache stores uncompressed bytes)
            accept_enc = request.headers.get("accept-encoding", "") if request else ""
            payload, cenc = _maybe_compress(cached_data, accept_enc, min_size=512)
            compression_info = f"{cenc}" if cenc else "uncompressed"
            logger.info(
                f"TILE {z}/{x}/{y}: runtime-cached-{compression_info}, <1ms, {len(payload):,}b"
            )
            headers = {
                "Cache-Control": TILE_CACHE_CONTROL,
                "Access-Control-Allow-Origin": "*",
                "X-Tile-Source": "elevation-data",
                "X-Cache": "HIT",
                "Vary": "Accept-Encoding",
            }
            if cenc:
                headers["Content-Encoding"] = cenc
            return Response(
                content=payload,
                media_type="application/octet-stream",
                headers=headers,
            )

        # Generate data asynchronously
        loop = asyncio.get_event_loop()
        elevation_data = await loop.run_in_executor(
            CPU_EXECUTOR, generate_elevation_data_sync, z, x, y
        )

        # Cache the generated data
        tile_cache.put(cache_key_format, z, x, y, elevation_data)

        # Negotiate compression per request (cache stores uncompressed bytes)
        accept_enc = request.headers.get("accept-encoding", "") if request else ""
        payload, cenc = _maybe_compress(elevation_data, accept_enc, min_size=512)

        latency_ms = (time.time() - start_time) * 1000
        compression_info = f"{cenc}" if cenc else "uncompressed"
        logger.info(
            f"TILE {z}/{x}/{y}: runtime-zst-{compression_info}, {latency_ms:.1f}ms, {len(payload):,}b"
        )
        headers = {
            "Cache-Control": TILE_CACHE_CONTROL,
            "Access-Control-Allow-Origin": "*",
            "X-Tile-Source": "elevation-data",
            "X-Cache": "MISS",
            "Vary": "Accept-Encoding",
        }
        if cenc:
            headers["Content-Encoding"] = cenc
        return Response(
            content=payload,
            media_type="application/octet-stream",
            headers=headers,
        )

    except Exception as e:
        logger.error(f"Error serving elevation data {z}/{x}/{y}: {e}")
        raise HTTPException(status_code=500, detail="Elevation data generation failed")


# ============================================================================
# COMPOSITE TILES (Optional - Combined Elevation + Flood)
# ============================================================================


@router.get("/composite/{water_level}/{z}/{x}/{y}.png")
@safe_tile_generation
@log_performance
async def get_composite_tile(
    water_level: float = Path(..., description="Water level in meters"),
    z: int = Path(..., description="Zoom level"),
    x: int = Path(..., description="Tile X coordinate"),
    y: int = Path(..., description="Tile Y coordinate"),
):
    """
    Serve composite tiles combining elevation and flood data.
    This is essentially the same as flood tiles but with explicit naming.
    """
    # For now, composite tiles are the same as flood tiles
    # In the future, could combine elevation grayscale with flood overlay
    return await get_flood_tile(water_level, z, x, y)


# ============================================================================
# HEALTH & DIAGNOSTICS
# ============================================================================


@router.get("/metadata")
async def get_tiles_metadata():
    """Get dynamic metadata for all tile types based on actual available data."""
    import sqlite3

    metadata = {
        "vector_tiles": {},
        "elevation_tiles": {
            "available_zoom_levels": list(
                range(SUPPORTED_ZOOM_RANGE[0], SUPPORTED_ZOOM_RANGE[1] + 1)
            ),
            "min_zoom": SUPPORTED_ZOOM_RANGE[0],
            "max_zoom": SUPPORTED_ZOOM_RANGE[1],
            "url_template": "/api/v1/tiles/elevation/{z}/{x}/{y}.png",
        },
        "flood_tiles": {
            "available_zoom_levels": list(
                range(SUPPORTED_ZOOM_RANGE[0], SUPPORTED_ZOOM_RANGE[1] + 1)
            ),
            "min_zoom": SUPPORTED_ZOOM_RANGE[0],
            "max_zoom": SUPPORTED_ZOOM_RANGE[1],
            "water_level_range": SUPPORTED_WATER_LEVEL_RANGE,
            "url_template": "/api/v1/tiles/flood/{water_level}/{z}/{x}/{y}.png",
        },
    }

    # Query actual MBTiles files for vector tile metadata
    from config import MAP_DATA_DIR

    mbtiles_path = MAP_DATA_DIR / "usa-complete.mbtiles"

    if mbtiles_path.exists():
        try:
            conn = sqlite3.connect(str(mbtiles_path))
            cursor = conn.cursor()

            # Get metadata from MBTiles
            cursor.execute("SELECT name, value FROM metadata")
            mbtiles_metadata = dict(cursor.fetchall())

            # Get actual zoom levels from tiles table
            cursor.execute("SELECT DISTINCT zoom_level FROM tiles ORDER BY zoom_level")
            available_zooms = [row[0] for row in cursor.fetchall()]

            conn.close()

            # Constrain to actual elevation data coverage area (N09-N31, W060-W119)
            elevation_bounds = [-119, 9, -60, 31]  # [west, south, east, north]
            elevation_center = [-89.5, 20]  # Center of elevation coverage area

            metadata["vector_tiles"] = {
                "available_zoom_levels": available_zooms,
                "min_zoom": min(available_zooms) if available_zooms else 0,
                "max_zoom": max(available_zooms) if available_zooms else 0,
                "bounds": elevation_bounds,  # Constrain to elevation coverage
                "center": elevation_center,  # Center on elevation coverage
                "url_template": "/api/v1/tiles/vector/usa/{z}/{x}/{y}.pbf",
                "sources": ["usa"],
            }

        except Exception as e:
            logger.error(f"Error reading MBTiles metadata: {e}")
            # Fallback if database can't be read
            metadata["vector_tiles"] = {
                "available_zoom_levels": [],
                "min_zoom": 0,
                "max_zoom": 0,
                "error": "Could not read vector tile metadata",
            }
    else:
        metadata["vector_tiles"] = {
            "available_zoom_levels": [],
            "min_zoom": 0,
            "max_zoom": 0,
            "error": "No vector tiles available",
        }

    return metadata


@router.get("/health")
async def tiles_v1_health():
    """Health check for v1 tile endpoints."""
    return {
        "status": "healthy",
        "version": "v1",
        "endpoints": {
            "vector": "/api/v1/tiles/vector/{source}/{z}/{x}/{y}.pbf",
            "elevation": "/api/v1/tiles/elevation/{z}/{x}/{y}.png",
            "flood": "/api/v1/tiles/flood/{water_level}/{z}/{x}/{y}.png",
            "composite": "/api/v1/tiles/composite/{water_level}/{z}/{x}/{y}.png",
        },
        "supported_zoom_range": SUPPORTED_ZOOM_RANGE,
        "supported_water_level_range": SUPPORTED_WATER_LEVEL_RANGE,
        "cache_age_seconds": TILE_CACHE_MAX_AGE,
    }
