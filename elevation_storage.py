#!/usr/bin/env python3
"""
Compressed elevation data storage system.

This module handles:
1. Compression/decompression of SRTM elevation tiles
2. Smart caching with LRU eviction
3. Fast tile lookup and loading
"""

import os
import time
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from collections import OrderedDict
import threading

import numpy as np
import rasterio
import zstandard as zstd
from rasterio.transform import rowcol


@dataclass
class TileInfo:
    """Information about a compressed tile."""
    tile_id: str
    bounds: Tuple[float, float, float, float]  # (left, bottom, right, top)
    transform: object
    shape: Tuple[int, int]
    compressed_path: str
    uncompressed_size: int
    compressed_size: int


class CompressedTileCache:
    """LRU cache for decompressed elevation tiles."""
    
    def __init__(self, max_tiles: int = 20, max_memory_mb: int = 500):
        self.max_tiles = max_tiles
        self.max_memory_mb = max_memory_mb
        self.cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self.cache_info: Dict[str, TileInfo] = {}
        self.lock = threading.RLock()
        self.decompressor = zstd.ZstdDecompressor()
        
        # Stats
        self.hits = 0
        self.misses = 0
        self.evictions = 0
    
    def get_tile(self, tile_id: str, compressed_data_dir: str) -> Optional[np.ndarray]:
        """Get a tile from cache, loading and decompressing if needed."""
        with self.lock:
            # Cache hit
            if tile_id in self.cache:
                self.hits += 1
                # Move to end (most recently used)
                self.cache.move_to_end(tile_id)
                return self.cache[tile_id]
            
            # Cache miss - load from disk
            self.misses += 1
            tile_data = self._load_compressed_tile(tile_id, compressed_data_dir)
            
            if tile_data is not None:
                self._add_to_cache(tile_id, tile_data)
                return tile_data
            
            return None
    
    def _load_compressed_tile(self, tile_id: str, compressed_data_dir: str) -> Optional[np.ndarray]:
        """Load and decompress a tile from disk."""
        compressed_path = os.path.join(compressed_data_dir, f"{tile_id}.zst")
        
        if not os.path.exists(compressed_path):
            return None
        
        try:
            start_time = time.time()
            
            # Read compressed data
            with open(compressed_path, 'rb') as f:
                compressed_data = f.read()
            
            # Decompress
            decompressed_data = self.decompressor.decompress(compressed_data)
            
            # Convert back to numpy array
            tile_data = np.frombuffer(decompressed_data, dtype=np.int16).reshape(3601, 3601)
            
            load_time = (time.time() - start_time) * 1000
            logging.debug(f"Loaded tile {tile_id} in {load_time:.1f}ms")
            
            return tile_data
            
        except Exception as e:
            logging.error(f"Failed to load compressed tile {tile_id}: {e}")
            return None
    
    def _add_to_cache(self, tile_id: str, tile_data: np.ndarray):
        """Add tile to cache, evicting old tiles if necessary."""
        # Add to cache
        self.cache[tile_id] = tile_data
        
        # Evict oldest tiles if we exceed limits
        while (len(self.cache) > self.max_tiles or 
               self._get_memory_usage_mb() > self.max_memory_mb):
            if not self.cache:
                break
                
            oldest_tile_id = next(iter(self.cache))
            del self.cache[oldest_tile_id]
            self.evictions += 1
            logging.debug(f"Evicted tile {oldest_tile_id} from cache")
    
    def _get_memory_usage_mb(self) -> float:
        """Calculate current memory usage in MB."""
        total_bytes = sum(tile.nbytes for tile in self.cache.values())
        return total_bytes / (1024 * 1024)
    
    def get_stats(self) -> Dict:
        """Get cache performance statistics."""
        total_requests = self.hits + self.misses
        hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0
        
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": hit_rate,
            "cached_tiles": len(self.cache),
            "memory_usage_mb": self._get_memory_usage_mb()
        }


class ElevationStorage:
    """Main interface for compressed elevation data storage."""
    
    def __init__(self, compressed_data_dir: str, cache_size: int = 20):
        self.compressed_data_dir = Path(compressed_data_dir)
        self.cache = CompressedTileCache(max_tiles=cache_size)
        self.tile_index: Dict[str, TileInfo] = {}
        
        # Build tile index
        self._build_tile_index()
    
    def _build_tile_index(self):
        """Build index of available compressed tiles."""
        if not self.compressed_data_dir.exists():
            logging.warning(f"Compressed data directory not found: {self.compressed_data_dir}")
            return
        
        for compressed_file in self.compressed_data_dir.glob("*.zst"):
            tile_id = compressed_file.stem  # Remove .zst extension
            
            # Try to load tile info from metadata file
            metadata_file = compressed_file.with_suffix('.json')
            if metadata_file.exists():
                # TODO: Load metadata (bounds, transform, etc.)
                pass
            
            self.tile_index[tile_id] = TileInfo(
                tile_id=tile_id,
                bounds=(0, 0, 0, 0),  # Will be populated when needed
                transform=None,
                shape=(3601, 3601),
                compressed_path=str(compressed_file),
                uncompressed_size=0,
                compressed_size=compressed_file.stat().st_size
            )
        
        logging.info(f"Indexed {len(self.tile_index)} compressed tiles")
    
    def get_elevation(self, latitude: float, longitude: float) -> Optional[float]:
        """Get elevation at a specific coordinate."""
        # Find which tile contains this coordinate
        tile_id = self._get_tile_id_for_coordinate(latitude, longitude)
        
        if not tile_id or tile_id not in self.tile_index:
            return None
        
        # Load tile data
        tile_data = self.cache.get_tile(tile_id, str(self.compressed_data_dir))
        
        if tile_data is None:
            return None
        
        # Convert coordinate to pixel position within the tile
        # SRTM tiles: each covers 1 degree, 3601x3601 pixels (1 arc-second resolution)
        tile_lat = int(np.floor(latitude))
        tile_lon = int(np.floor(longitude)) if longitude >= 0 else int(np.ceil(longitude))
        
        # Fractional part within the tile (0-1)
        frac_lat = latitude - tile_lat
        frac_lon = longitude - tile_lon if longitude >= 0 else longitude - tile_lon
        
        # Convert to pixel coordinates (0-3600)
        # Note: SRTM arrays are top-to-bottom, so we flip the latitude
        pixel_row = int((1.0 - frac_lat) * 3600)  # Flip vertically
        pixel_col = int(abs(frac_lon) * 3600)  # Handle negative longitude
        
        # Bounds check
        if 0 <= pixel_row < 3601 and 0 <= pixel_col < 3601:
            elevation = float(tile_data[pixel_row, pixel_col])
            # Check for SRTM no-data values
            if elevation in [-32768, -32767]:
                return None
            return elevation
        
        return None
    
    def _get_tile_id_for_coordinate(self, latitude: float, longitude: float) -> Optional[str]:
        """Get tile ID that contains the given coordinate."""
        # SRTM tile naming: n{lat}_w{lon}_1arc_v3
        lat_int = int(np.floor(latitude))
        lon_int = int(np.floor(abs(longitude)))  # SRTM uses positive values for west
        
        # Format tile ID
        lat_str = f"n{lat_int:02d}" if latitude >= 0 else f"s{abs(lat_int):02d}"
        lon_str = f"w{lon_int:03d}" if longitude < 0 else f"e{lon_int:03d}"
        
        tile_id = f"{lat_str}_{lon_str}_1arc_v3"
        return tile_id
    
    def preload_tiles_for_area(self, center_lat: float, center_lon: float, radius_deg: float = 0.5):
        """Preload tiles for an area around the center coordinate."""
        min_lat = center_lat - radius_deg
        max_lat = center_lat + radius_deg
        min_lon = center_lon - radius_deg
        max_lon = center_lon + radius_deg
        
        # Find all tiles that intersect this area
        tiles_to_load = set()
        
        for lat in np.arange(np.floor(min_lat), np.ceil(max_lat) + 1):
            for lon in np.arange(np.floor(min_lon), np.ceil(max_lon) + 1):
                tile_id = self._get_tile_id_for_coordinate(lat, lon)
                if tile_id and tile_id in self.tile_index:
                    tiles_to_load.add(tile_id)
        
        # Load tiles in background
        for tile_id in tiles_to_load:
            self.cache.get_tile(tile_id, str(self.compressed_data_dir))
        
        logging.info(f"Preloaded {len(tiles_to_load)} tiles for area around ({center_lat}, {center_lon})")
    
    def get_cache_stats(self) -> Dict:
        """Get cache performance statistics."""
        return self.cache.get_stats()