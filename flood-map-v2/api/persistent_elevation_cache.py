"""
Persistent Elevation Cache - Eliminate zstd decompression bottleneck
Keeps decompressed elevation arrays in memory across requests.
"""

import os
import json
import time
import threading
import psutil
from pathlib import Path
from typing import Optional, Dict, Tuple
import numpy as np
import zstandard as zstd
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from collections import OrderedDict

logger = logging.getLogger(__name__)

@dataclass
class ElevationCacheEntry:
    """Cached elevation data with metadata."""
    array: np.ndarray
    metadata: dict
    last_accessed: float
    access_count: int
    file_size_mb: float

class PersistentElevationCache:
    """
    High-performance persistent elevation cache.
    Keeps frequently used elevation arrays decompressed in memory.
    """
    
    def __init__(self, 
                 data_dir: str = "/Users/davidrose/git/floodmap/compressed_data/usa",
                 max_memory_gb: float = 4.0,  # Use up to 4GB for cache
                 preload_cores: int = None):
        
        self.data_dir = Path(data_dir)
        self.max_memory_bytes = int(max_memory_gb * 1024 * 1024 * 1024)
        self.preload_cores = preload_cores or min(8, os.cpu_count())
        
        # Thread-safe cache
        self.cache: Dict[str, ElevationCacheEntry] = OrderedDict()
        self.cache_lock = threading.RLock()
        self.current_memory_usage = 0
        
        # Decompression worker pool - separate from tile generation
        self.decompression_pool = ThreadPoolExecutor(
            max_workers=self.preload_cores, 
            thread_name_prefix="elevation-decomp"
        )
        
        # Statistics
        self.stats = {
            'hits': 0,
            'misses': 0, 
            'decompressions': 0,
            'evictions': 0,
            'preloads': 0
        }
        
        logger.info(f"🚀 Persistent elevation cache: {max_memory_gb:.1f}GB limit, {self.preload_cores} decompression cores")
        
        # Start background preloading of common files
        self._start_background_preloading()
    
    def _start_background_preloading(self):
        """Preload most commonly accessed elevation files."""
        def preload_common_areas():
            # Common areas: Tampa, Miami, NYC, LA, Houston
            common_coords = [
                (27, -82),  # Tampa
                (25, -80),  # Miami  
                (40, -74),  # NYC
                (34, -118), # LA
                (29, -95),  # Houston
                (32, -117), # San Diego
                (47, -122), # Seattle
                (41, -87),  # Chicago
            ]
            
            futures = []
            for lat, lon in common_coords:
                future = self.decompression_pool.submit(self._preload_file_async, lat, lon)
                futures.append(future)
            
            # Wait for preloading to complete
            loaded_count = 0
            for future in as_completed(futures):
                try:
                    if future.result():
                        loaded_count += 1
                        self.stats['preloads'] += 1
                except Exception as e:
                    logger.warning(f"Preload failed: {e}")
            
            logger.info(f"✅ Preloaded {loaded_count}/{len(common_coords)} common elevation areas")
        
        # Start preloading in background
        threading.Thread(target=preload_common_areas, daemon=True).start()
    
    def _preload_file_async(self, lat: int, lon: int) -> bool:
        """Preload a specific elevation file by coordinates."""
        filename = self._generate_filename(lat, lon)
        file_path = self.data_dir / filename
        
        if not file_path.exists():
            return False
        
        try:
            # Load and cache
            entry = self._load_elevation_file(file_path)
            if entry:
                with self.cache_lock:
                    self.cache[str(file_path)] = entry
                    self.current_memory_usage += entry.file_size_mb * 1024 * 1024
                    self._enforce_memory_limit()
                return True
        except Exception as e:
            logger.warning(f"Failed to preload {filename}: {e}")
        
        return False
    
    def _generate_filename(self, lat: int, lon: int) -> str:
        """Generate elevation filename from coordinates (O(1) lookup)."""
        lat_letter = 'n' if lat >= 0 else 's'
        lon_letter = 'w' if lon < 0 else 'e'
        return f"{lat_letter}{abs(lat):02d}_{lon_letter}{abs(lon):03d}_1arc_v3.zst"
    
    def get_elevation_array(self, file_path: Path) -> Optional[Tuple[np.ndarray, dict]]:
        """
        Get elevation array - either from cache or load on demand.
        This replaces the slow zstd decompression in elevation_loader.py
        """
        cache_key = str(file_path)
        current_time = time.time()
        
        # Check cache first
        with self.cache_lock:
            if cache_key in self.cache:
                entry = self.cache[cache_key]
                entry.last_accessed = current_time
                entry.access_count += 1
                
                # Move to end for LRU
                self.cache.move_to_end(cache_key)
                self.stats['hits'] += 1
                
                return (entry.array.copy(), entry.metadata)  # Return copy for safety
        
        # Cache miss - load the file
        self.stats['misses'] += 1
        entry = self._load_elevation_file(file_path)
        
        if entry is None:
            return None
        
        # Add to cache
        with self.cache_lock:
            self.cache[cache_key] = entry
            self.current_memory_usage += entry.file_size_mb * 1024 * 1024
            self._enforce_memory_limit()
        
        return (entry.array.copy(), entry.metadata)
    
    def _load_elevation_file(self, file_path: Path) -> Optional[ElevationCacheEntry]:
        """Load and decompress elevation file."""
        try:
            start_time = time.perf_counter()
            
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
            
            # Handle both metadata formats
            if 'shape' in metadata:
                height, width = metadata['shape']
            else:
                height, width = metadata['height'], metadata['width']
            
            elevation_array = np.frombuffer(decompressed, dtype=np.int16).reshape(height, width)
            
            # Calculate memory usage
            array_size_mb = elevation_array.nbytes / (1024 * 1024)
            
            end_time = time.perf_counter()
            decomp_time = (end_time - start_time) * 1000
            
            logger.debug(f"Decompressed {file_path.name} in {decomp_time:.1f}ms ({array_size_mb:.1f}MB)")
            self.stats['decompressions'] += 1
            
            return ElevationCacheEntry(
                array=elevation_array,
                metadata=metadata,
                last_accessed=time.time(),
                access_count=1,
                file_size_mb=array_size_mb
            )
            
        except Exception as e:
            logger.error(f"Failed to load elevation data from {file_path}: {e}")
            return None
    
    def _enforce_memory_limit(self):
        """Enforce memory limit by evicting least recently used entries."""
        while self.current_memory_usage > self.max_memory_bytes and self.cache:
            # Remove oldest entry (LRU)
            oldest_key, oldest_entry = self.cache.popitem(last=False)
            self.current_memory_usage -= oldest_entry.file_size_mb * 1024 * 1024
            self.stats['evictions'] += 1
            
            logger.debug(f"Evicted {oldest_key} (accessed {oldest_entry.access_count} times)")
    
    def preload_area(self, lat_center: float, lon_center: float, radius_degrees: float = 1.0):
        """
        Preload elevation files for an area.
        Called when user pans to new location.
        """
        lat_min = int(lat_center - radius_degrees)
        lat_max = int(lat_center + radius_degrees)
        lon_min = int(lon_center - radius_degrees) 
        lon_max = int(lon_center + radius_degrees)
        
        futures = []
        for lat in range(lat_min, lat_max + 1):
            for lon in range(lon_min, lon_max + 1):
                future = self.decompression_pool.submit(self._preload_file_async, lat, lon)
                futures.append(future)
        
        # Don't wait for completion - let it happen in background
        logger.info(f"🔄 Preloading {len(futures)} elevation files around ({lat_center:.2f}, {lon_center:.2f})")
    
    def get_stats(self) -> dict:
        """Get cache performance statistics."""
        with self.cache_lock:
            total_requests = self.stats['hits'] + self.stats['misses']
            hit_rate = self.stats['hits'] / max(total_requests, 1)
            
            return {
                'cache_size': len(self.cache),
                'memory_usage_mb': self.current_memory_usage / (1024 * 1024),
                'memory_limit_mb': self.max_memory_bytes / (1024 * 1024),
                'hit_rate': hit_rate,
                'total_requests': total_requests,
                'decompression_cores': self.preload_cores,
                **self.stats
            }
    
    def clear_cache(self):
        """Clear all cached data."""
        with self.cache_lock:
            self.cache.clear()
            self.current_memory_usage = 0
            self.stats = {k: 0 for k in self.stats}
        
        logger.info("🧹 Elevation cache cleared")
    
    def shutdown(self):
        """Shutdown the cache and worker pools."""
        self.decompression_pool.shutdown(wait=True)
        self.clear_cache()
        logger.info("🛑 Persistent elevation cache shutdown")

# Global cache instance - uses up to 4GB RAM
persistent_elevation_cache = PersistentElevationCache(max_memory_gb=4.0)