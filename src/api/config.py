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
# These paths are ALWAYS the same inside the container - never configurable
ELEVATION_DATA_DIR = Path("/app/data/elevation")
MAP_DATA_DIR = Path("/app/data/maps") 
PRECOMPRESSED_TILES_DIR = Path("/app/data/precompressed")

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
    ELEVATION_DATA_DIR / "usa",
    ELEVATION_DATA_DIR / "usa_unified", 
    ELEVATION_DATA_DIR / "tampa"
]

VECTOR_TILE_PATHS = [
    MAP_DATA_DIR / "usa-complete.mbtiles",
    MAP_DATA_DIR / "tampa.mbtiles"
]

# Health check paths
HEALTH_CHECK_DIRS = [
    str(ELEVATION_DATA_DIR),
    str(MAP_DATA_DIR)
]
