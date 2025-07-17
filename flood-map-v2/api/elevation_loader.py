"""
Elevation data loader for dynamic tile generation.
Reads compressed elevation data and provides tile-based access.
"""

import os
import json
import math
import zstandard as zstd
import numpy as np
from pathlib import Path
from typing import Optional, Tuple, Dict
import logging

logger = logging.getLogger(__name__)


class ElevationDataLoader:
    """Load and query elevation data for tile generation."""
    
    def __init__(self, data_dir: str = "/Users/davidrose/git/floodmap/compressed_data/usa"):
        self.data_dir = Path(data_dir)
        self.cache = {}  # Simple in-memory cache for loaded tiles
        self.max_cache_size = 50  # Keep 50 elevation arrays in memory
        
    def deg2num(self, lat_deg: float, lon_deg: float, zoom: int) -> Tuple[int, int]:
        """Convert lat/lon to tile numbers using Web Mercator projection."""
        lat_rad = math.radians(lat_deg)
        n = 2.0 ** zoom
        xtile = int((lon_deg + 180.0) / 360.0 * n)
        ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        return (xtile, ytile)
    
    def num2deg(self, xtile: int, ytile: int, zoom: int) -> Tuple[float, float, float, float]:
        """Convert tile numbers to lat/lon bounds."""
        n = 2.0 ** zoom
        lon_deg_left = xtile / n * 360.0 - 180.0
        lon_deg_right = (xtile + 1) / n * 360.0 - 180.0
        
        lat_deg_top = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ytile / n))))
        lat_deg_bottom = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ytile + 1) / n))))
        
        return (lat_deg_top, lat_deg_bottom, lon_deg_left, lon_deg_right)
    
    def find_elevation_files_for_tile(self, lat_top: float, lat_bottom: float, 
                                     lon_left: float, lon_right: float) -> list:
        """Find elevation files that overlap with the given tile bounds."""
        overlapping_files = []
        
        # Scan through available elevation files
        for file_path in self.data_dir.glob("*.zst"):
            # Parse coordinate from filename (e.g., n27_w082_1arc_v3.zst)
            filename = file_path.stem
            parts = filename.split('_')
            
            if len(parts) >= 2:
                try:
                    # Extract lat/lon from filename
                    lat_str = parts[0]  # e.g., "n27" or "s27"
                    lon_str = parts[1]  # e.g., "w082" or "e082"
                    
                    file_lat = int(lat_str[1:])
                    if lat_str[0] == 's':
                        file_lat = -file_lat
                        
                    file_lon = int(lon_str[1:])
                    if lon_str[0] == 'w':
                        file_lon = -file_lon
                    
                    # Each file covers 1 degree
                    file_lat_top = file_lat + 1
                    file_lat_bottom = file_lat
                    file_lon_left = file_lon
                    file_lon_right = file_lon + 1
                    
                    # Check for overlap
                    if (file_lat_bottom < lat_top and file_lat_top > lat_bottom and
                        file_lon_left < lon_right and file_lon_right > lon_left):
                        overlapping_files.append(file_path)
                        
                except (ValueError, IndexError):
                    continue
                    
        return overlapping_files
    
    def load_elevation_data(self, file_path: Path) -> Optional[Tuple[np.ndarray, dict]]:
        """Load elevation data from compressed file."""
        cache_key = str(file_path)
        
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        try:
            # Load compressed data
            with open(file_path, 'rb') as f:
                compressed_data = f.read()
            
            # Load metadata
            metadata_path = file_path.with_suffix('.json')
            if not metadata_path.exists():
                logger.warning(f"No metadata found for {file_path}")
                return None
                
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            
            # Decompress elevation data
            dctx = zstd.ZstdDecompressor()
            decompressed = dctx.decompress(compressed_data)
            elevation_array = np.frombuffer(decompressed, dtype=np.int16).reshape(
                metadata['height'], metadata['width']
            )
            
            # Cache management
            if len(self.cache) >= self.max_cache_size:
                # Remove oldest entry (simple FIFO)
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
            
            self.cache[cache_key] = (elevation_array, metadata)
            return (elevation_array, metadata)
            
        except Exception as e:
            logger.error(f"Failed to load elevation data from {file_path}: {e}")
            return None
    
    def get_elevation_for_tile(self, xtile: int, ytile: int, zoom: int, 
                              tile_size: int = 256) -> Optional[np.ndarray]:
        """
        Get elevation data for a specific tile.
        
        Returns:
            2D numpy array with elevation values, or None if no data available
        """
        # Cache key for this specific tile request
        tile_cache_key = f"tile_{xtile}_{ytile}_{zoom}_{tile_size}"
        if tile_cache_key in self.cache:
            return self.cache[tile_cache_key]
        
        # Get tile bounds
        lat_top, lat_bottom, lon_left, lon_right = self.num2deg(xtile, ytile, zoom)
        
        # Find overlapping elevation files
        overlapping_files = self.find_elevation_files_for_tile(
            lat_top, lat_bottom, lon_left, lon_right
        )
        
        if not overlapping_files:
            logger.debug(f"No elevation files found for tile {xtile}/{ytile}/{zoom}")
            return None
        
        # Handle multiple overlapping files with proper mosaicking
        tile_data = self._mosaic_elevation_files(
            overlapping_files, lat_top, lat_bottom, lon_left, lon_right, tile_size
        )
        
        # Cache the result
        if tile_data is not None:
            if len(self.cache) >= self.max_cache_size:
                # Remove oldest tile cache entry
                oldest_key = next((k for k in self.cache.keys() if k.startswith("tile_")), None)
                if oldest_key:
                    del self.cache[oldest_key]
            
            self.cache[tile_cache_key] = tile_data
        
        return tile_data
    
    def _mosaic_elevation_files(self, files: list, lat_top: float, lat_bottom: float,
                               lon_left: float, lon_right: float, tile_size: int) -> Optional[np.ndarray]:
        """Mosaic multiple elevation files into a single tile."""
        if len(files) == 1:
            # Single file - use optimized path
            return self._extract_tile_from_file(files[0], lat_top, lat_bottom, lon_left, lon_right, tile_size)
        
        # Multiple files - create mosaic
        result_tile = np.full((tile_size, tile_size), -32768, dtype=np.int16)  # NoData value
        
        for file_path in files:
            tile_data = self._extract_tile_from_file(file_path, lat_top, lat_bottom, lon_left, lon_right, tile_size)
            if tile_data is not None:
                # Overlay non-nodata values
                valid_mask = tile_data != -32768
                result_tile[valid_mask] = tile_data[valid_mask]
        
        # Return None if all NoData
        if np.all(result_tile == -32768):
            return None
            
        return result_tile
    
    def _extract_tile_from_file(self, file_path: Path, lat_top: float, lat_bottom: float,
                               lon_left: float, lon_right: float, tile_size: int) -> Optional[np.ndarray]:
        """Extract tile data from a single elevation file."""
        elevation_data = self.load_elevation_data(file_path)
        if elevation_data is None:
            return None
            
        elevation_array, metadata = elevation_data
        
        # Convert tile bounds to array indices
        file_bounds = metadata['bounds']
        file_lat_top = file_bounds['north']
        file_lat_bottom = file_bounds['south'] 
        file_lon_left = file_bounds['west']
        file_lon_right = file_bounds['east']
        
        # Calculate overlap region
        overlap_lat_top = min(lat_top, file_lat_top)
        overlap_lat_bottom = max(lat_bottom, file_lat_bottom)
        overlap_lon_left = max(lon_left, file_lon_left)
        overlap_lon_right = min(lon_right, file_lon_right)
        
        # Check if there's actual overlap
        if overlap_lat_bottom >= overlap_lat_top or overlap_lon_left >= overlap_lon_right:
            return None
        
        # Calculate array indices for overlap region
        height, width = elevation_array.shape
        
        # Map overlap bounds to array indices
        y_top = max(0, int((file_lat_top - overlap_lat_top) / (file_lat_top - file_lat_bottom) * height))
        y_bottom = min(height, int((file_lat_top - overlap_lat_bottom) / (file_lat_top - file_lat_bottom) * height))
        x_left = max(0, int((overlap_lon_left - file_lon_left) / (file_lon_right - file_lon_left) * width))
        x_right = min(width, int((overlap_lon_right - file_lon_left) / (file_lon_right - file_lon_left) * width))
        
        if y_bottom <= y_top or x_right <= x_left:
            return None
        
        # Extract data
        tile_data = elevation_array[y_top:y_bottom, x_left:x_right]
        
        # Resize to standard tile size using high-quality resampling
        if tile_data.shape != (tile_size, tile_size):
            from PIL import Image
            # Handle potential data type issues
            if tile_data.dtype == np.int16:
                # Convert to float for better interpolation, then back to int16
                img = Image.fromarray(tile_data.astype(np.float32))
                img = img.resize((tile_size, tile_size), Image.LANCZOS)  # Higher quality resampling
                tile_data = np.array(img, dtype=np.int16)
            else:
                img = Image.fromarray(tile_data)
                img = img.resize((tile_size, tile_size), Image.LANCZOS)
                tile_data = np.array(img)
        
        return tile_data


# Global instance
elevation_loader = ElevationDataLoader()