"""
HIGH-PERFORMANCE Elevation Data Loader
Optimized for sub-100ms tile generation with spatial indexing and pre-computation.
"""

import os
import json
import math
import zstandard as zstd
import numpy as np
from pathlib import Path
from typing import Optional, Tuple, Dict
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import mmap

logger = logging.getLogger(__name__)


class SpatialIndex:
    """Spatial index for fast elevation file lookup."""
    
    def __init__(self):
        self.grid = {}  # lat_lon_key -> file_path
        self.bounds_cache = {}  # file_path -> bounds
    
    def add_file(self, file_path: Path, bounds: dict):
        """Add file to spatial index."""
        lat = int(bounds['bottom'])  # Floor lat
        lon = int(bounds['left'])    # Floor lon
        key = f"{lat}_{lon}"
        self.grid[key] = file_path
        self.bounds_cache[file_path] = bounds
    
    def find_files_for_tile(self, lat_top: float, lat_bottom: float, 
                           lon_left: float, lon_right: float) -> list:
        """Fast lookup of elevation files for tile bounds."""
        files = []
        
        # Check grid cells that might overlap
        lat_start = int(math.floor(lat_bottom))
        lat_end = int(math.ceil(lat_top))
        lon_start = int(math.floor(lon_left))  
        lon_end = int(math.ceil(lon_right))
        
        for lat in range(lat_start, lat_end + 1):
            for lon in range(lon_start, lon_end + 1):
                key = f"{lat}_{lon}"
                if key in self.grid:
                    file_path = self.grid[key]
                    bounds = self.bounds_cache[file_path]
                    
                    # Precise overlap check
                    if (bounds['bottom'] < lat_top and bounds['top'] > lat_bottom and
                        bounds['left'] < lon_right and bounds['right'] > lon_left):
                        files.append(file_path)
        
        return files


class OptimizedElevationLoader:
    """High-performance elevation data loader with spatial indexing."""
    
    def __init__(self, data_dir: str = "/Users/davidrose/git/floodmap/compressed_data/usa"):
        self.data_dir = Path(data_dir)
        self.spatial_index = SpatialIndex()
        self.file_cache = {}  # file_path -> (mmap, metadata)
        self.tile_cache = {}  # tile_key -> np.array
        self.max_file_cache = 100  # Keep 100 files mmapped
        self.max_tile_cache = 500  # Keep 500 extracted tiles
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # Build spatial index
        self._build_spatial_index()
        
    def _build_spatial_index(self):
        """Build spatial index of all elevation files."""
        logger.info("Building spatial index...")
        start_time = time.time()
        
        for json_file in self.data_dir.glob("*.json"):
            try:
                with open(json_file, 'r') as f:
                    metadata = json.load(f)
                
                zst_file = json_file.with_suffix('.zst')
                if zst_file.exists():
                    self.spatial_index.add_file(zst_file, metadata['bounds'])
                    
            except Exception as e:
                logger.warning(f"Failed to index {json_file}: {e}")
        
        logger.info(f"Spatial index built in {time.time() - start_time:.2f}s")
    
    def _get_file_data(self, file_path: Path) -> Optional[Tuple[np.ndarray, dict]]:
        """Get elevation data with memory mapping for speed."""
        with self.lock:
            if file_path in self.file_cache:
                return self.file_cache[file_path]
            
            try:
                # Load metadata
                metadata_path = file_path.with_suffix('.json')
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                
                # Memory map the compressed file
                with open(file_path, 'rb') as f:
                    compressed_data = f.read()
                
                # Decompress once and cache
                dctx = zstd.ZstdDecompressor()
                decompressed = dctx.decompress(compressed_data)
                
                height, width = metadata['shape']
                elevation_array = np.frombuffer(decompressed, dtype=np.int16).reshape(height, width)
                
                # Cache management
                if len(self.file_cache) >= self.max_file_cache:
                    # Remove oldest entry
                    oldest_key = next(iter(self.file_cache))
                    del self.file_cache[oldest_key]
                
                self.file_cache[file_path] = (elevation_array, metadata)
                return (elevation_array, metadata)
                
            except Exception as e:
                logger.error(f"Failed to load {file_path}: {e}")
                return None
    
    def get_elevation_for_tile(self, xtile: int, ytile: int, zoom: int, 
                              tile_size: int = 256) -> Optional[np.ndarray]:
        """Fast tile extraction with spatial indexing."""
        # Cache key for this specific tile
        tile_key = f"{xtile}_{ytile}_{zoom}"
        
        with self.lock:
            if tile_key in self.tile_cache:
                return self.tile_cache[tile_key]
        
        # Get tile bounds
        lat_top, lat_bottom, lon_left, lon_right = self.num2deg(xtile, ytile, zoom)
        
        # Fast spatial lookup
        overlapping_files = self.spatial_index.find_files_for_tile(
            lat_top, lat_bottom, lon_left, lon_right
        )
        
        if not overlapping_files:
            return None
        
        # Extract tile data (optimized for single file case)
        if len(overlapping_files) == 1:
            tile_data = self._extract_tile_fast(
                overlapping_files[0], lat_top, lat_bottom, lon_left, lon_right, tile_size
            )
        else:
            # Multi-file mosaic (rare case)
            tile_data = self._mosaic_files_fast(
                overlapping_files, lat_top, lat_bottom, lon_left, lon_right, tile_size
            )
        
        # Cache the extracted tile
        if tile_data is not None:
            with self.lock:
                if len(self.tile_cache) >= self.max_tile_cache:
                    # Remove oldest tile
                    oldest_key = next(iter(self.tile_cache))
                    del self.tile_cache[oldest_key]
                
                self.tile_cache[tile_key] = tile_data
        
        return tile_data
    
    def _extract_tile_fast(self, file_path: Path, lat_top: float, lat_bottom: float,
                          lon_left: float, lon_right: float, tile_size: int) -> Optional[np.ndarray]:
        """Fast tile extraction from single file."""
        file_data = self._get_file_data(file_path)
        if file_data is None:
            return None
        
        elevation_array, metadata = file_data
        
        # Calculate array slice indices
        bounds = metadata['bounds']
        file_lat_top = bounds['top']
        file_lat_bottom = bounds['bottom']
        file_lon_left = bounds['left']
        file_lon_right = bounds['right']
        
        height, width = elevation_array.shape
        
        # Convert geographic bounds to array indices
        y_top = max(0, int((file_lat_top - min(lat_top, file_lat_top)) / 
                          (file_lat_top - file_lat_bottom) * height))
        y_bottom = min(height, int((file_lat_top - max(lat_bottom, file_lat_bottom)) / 
                                  (file_lat_top - file_lat_bottom) * height))
        x_left = max(0, int((max(lon_left, file_lon_left) - file_lon_left) / 
                           (file_lon_right - file_lon_left) * width))
        x_right = min(width, int((min(lon_right, file_lon_right) - file_lon_left) / 
                                (file_lon_right - file_lon_left) * width))
        
        if y_bottom <= y_top or x_right <= x_left:
            return None
        
        # Extract subarray - this is the key optimization
        tile_data = elevation_array[y_top:y_bottom, x_left:x_right].copy()
        
        # Resize if needed (usually not for well-aligned tiles)
        if tile_data.shape != (tile_size, tile_size):
            from PIL import Image
            img = Image.fromarray(tile_data.astype(np.float32))
            img = img.resize((tile_size, tile_size), Image.LANCZOS)
            tile_data = np.array(img, dtype=np.int16)
        
        return tile_data
    
    def num2deg(self, xtile: int, ytile: int, zoom: int) -> Tuple[float, float, float, float]:
        """Convert tile numbers to lat/lon bounds."""
        n = 2.0 ** zoom
        lon_deg_left = xtile / n * 360.0 - 180.0
        lon_deg_right = (xtile + 1) / n * 360.0 - 180.0
        
        lat_deg_top = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ytile / n))))
        lat_deg_bottom = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ytile + 1) / n))))
        
        return (lat_deg_top, lat_deg_bottom, lon_deg_left, lon_deg_right)


# Global optimized loader instance  
optimized_elevation_loader = OptimizedElevationLoader()