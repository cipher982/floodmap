"""
Centralized configuration management for FloodMap API.
All environment variables and constants are defined here.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Container paths (fixed internal structure)
# These paths are ALWAYS the same inside containers - never configurable
ELEVATION_SOURCE_DIR = Path("/app/data/elevation-source")  # Raw SRTM files (.zst)
ELEVATION_TILES_DIR = Path("/app/data/elevation-tiles")    # Precompressed tiles (.u16.br)
BASE_MAPS_DIR = Path("/app/data/base-maps")               # Background maps (.mbtiles)

# Legacy compatibility - remove after updating dependent code
ELEVATION_DATA_DIR = ELEVATION_SOURCE_DIR
MAP_DATA_DIR = BASE_MAPS_DIR
PRECOMPRESSED_TILES_DIR = ELEVATION_TILES_DIR

# Legacy compatibility - remove these after updating dependent code
PROJECT_ROOT = Path("/app")  # Fixed container root
COMPRESSED_DATA_DIR = ELEVATION_DATA_DIR  # Same as elevation data

# Server configuration
API_PORT = int(os.getenv("API_PORT"))
TILESERVER_PORT = int(os.getenv("TILESERVER_PORT"))
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT"))
# Use 127.0.0.1 instead of localhost for more reliable connection to Docker
TILESERVER_URL = os.getenv("TILESERVER_URL")

# Environment detection
ENVIRONMENT = os.getenv("ENVIRONMENT")
IS_DEVELOPMENT = ENVIRONMENT.lower() in ["development", "dev", "local"]
IS_PRODUCTION = ENVIRONMENT.lower() in ["production", "prod"]

# Cache configuration - environment aware
ELEVATION_CACHE_SIZE = int(os.getenv("ELEVATION_CACHE_SIZE"))
TILE_CACHE_SIZE = int(os.getenv("TILE_CACHE_SIZE"))

# HTTP Cache settings - NO CACHING in development!
if IS_DEVELOPMENT:
    TILE_CACHE_MAX_AGE = 0  # No browser caching in development
    TILE_CACHE_TTL = None   # Server cache TTL may be overridden to short-lived in tile_cache
    TILE_CACHE_CONTROL = "no-cache, no-store, must-revalidate"
else:
    TILE_CACHE_MAX_AGE = 31536000  # 1 year for production
    TILE_CACHE_TTL = None  # Infinite server cache for production  
    TILE_CACHE_CONTROL = f"public, max-age={TILE_CACHE_MAX_AGE}, immutable"

# Data processing constants
NODATA_VALUE = int(os.getenv("NODATA_VALUE"))
VECTOR_TILE_MIN_SIZE = int(os.getenv("VECTOR_TILE_MIN_SIZE"))

# Tile configuration
TILE_SIZE = 256
MAX_ZOOM = 18
MIN_ZOOM = 0

# Water level configuration
MIN_WATER_LEVEL = -10.0
MAX_WATER_LEVEL = 1000.0

# Specific data paths - fixed container locations  
ELEVATION_DIRS = [
    ELEVATION_SOURCE_DIR / "usa",
    ELEVATION_SOURCE_DIR / "usa_unified"
]

BASE_MAP_PATHS = [
    BASE_MAPS_DIR / "usa-complete.mbtiles"
]

# Legacy compatibility
VECTOR_TILE_PATHS = BASE_MAP_PATHS

# Health check paths
HEALTH_CHECK_DIRS = [
    str(ELEVATION_SOURCE_DIR),
    str(ELEVATION_TILES_DIR), 
    str(BASE_MAPS_DIR)
]
