"""
Centralized configuration management for FloodMap API.
All environment variables and constants are defined here.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Project structure
PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/Users/davidrose/git/floodmap"))
ELEVATION_DATA_DIR = PROJECT_ROOT / os.getenv("ELEVATION_DATA_DIR", "output/elevation")
COMPRESSED_DATA_DIR = PROJECT_ROOT / os.getenv("COMPRESSED_DATA_DIR", "compressed_data")
MAP_DATA_DIR = PROJECT_ROOT / os.getenv("MAP_DATA_DIR", "map_data")

# Server configuration
API_PORT = int(os.getenv("API_PORT", "5003"))
TILESERVER_PORT = int(os.getenv("TILESERVER_PORT", "8080"))
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", "3000"))
TILESERVER_URL = os.getenv("TILESERVER_URL", f"http://localhost:{TILESERVER_PORT}")

# Cache configuration
ELEVATION_CACHE_SIZE = int(os.getenv("ELEVATION_CACHE_SIZE", "50"))
TILE_CACHE_SIZE = int(os.getenv("TILE_CACHE_SIZE", "1000"))

# Data processing constants
NODATA_VALUE = int(os.getenv("NODATA_VALUE", "-32768"))
VECTOR_TILE_MIN_SIZE = int(os.getenv("VECTOR_TILE_MIN_SIZE", "100"))

# Tile configuration
TILE_SIZE = 256
MAX_ZOOM = 18
MIN_ZOOM = 0

# Water level configuration
MIN_WATER_LEVEL = -10.0
MAX_WATER_LEVEL = 1000.0

# Specific data paths
ELEVATION_DIRS = [
    COMPRESSED_DATA_DIR / "usa",
    COMPRESSED_DATA_DIR / "usa_unified", 
    COMPRESSED_DATA_DIR / "tampa"
]

VECTOR_TILE_PATHS = [
    MAP_DATA_DIR / "usa-complete.mbtiles",
    MAP_DATA_DIR / "tampa.mbtiles"
]

# Health check paths
HEALTH_CHECK_DIRS = [
    str(COMPRESSED_DATA_DIR),
    str(MAP_DATA_DIR)
]