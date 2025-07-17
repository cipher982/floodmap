"""
Simple in-memory tile cache for performance optimization.
"""

import time
import threading
from typing import Optional, Tuple
from dataclasses import dataclass


@dataclass
class CacheEntry:
    """Single cache entry with timestamp."""
    tile_data: bytes
    timestamp: float
    water_level: float
    

class TileCache:
    """Simple LRU cache for generated tiles."""
    
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache = {}
        self.access_order = []  # For LRU eviction
        self.lock = threading.RLock()
    
    def _make_key(self, water_level: float, z: int, x: int, y: int) -> str:
        """Create cache key from tile coordinates and water level."""
        return f"{water_level:.1f}:{z}:{x}:{y}"
    
    def get(self, water_level: float, z: int, x: int, y: int) -> Optional[bytes]:
        """Get cached tile if available and not expired."""
        key = self._make_key(water_level, z, x, y)
        
        with self.lock:
            if key not in self.cache:
                return None
            
            entry = self.cache[key]
            
            # Check if expired
            if time.time() - entry.timestamp > self.ttl_seconds:
                del self.cache[key]
                if key in self.access_order:
                    self.access_order.remove(key)
                return None
            
            # Update access order for LRU
            if key in self.access_order:
                self.access_order.remove(key)
            self.access_order.append(key)
            
            return entry.tile_data
    
    def put(self, water_level: float, z: int, x: int, y: int, tile_data: bytes):
        """Cache generated tile."""
        key = self._make_key(water_level, z, x, y)
        
        with self.lock:
            # Remove oldest entries if cache is full
            while len(self.cache) >= self.max_size:
                if self.access_order:
                    oldest_key = self.access_order.pop(0)
                    if oldest_key in self.cache:
                        del self.cache[oldest_key]
                else:
                    break
            
            # Add new entry
            self.cache[key] = CacheEntry(
                tile_data=tile_data,
                timestamp=time.time(),
                water_level=water_level
            )
            
            # Update access order
            if key in self.access_order:
                self.access_order.remove(key)
            self.access_order.append(key)
    
    def clear(self):
        """Clear all cached tiles."""
        with self.lock:
            self.cache.clear()
            self.access_order.clear()
    
    def stats(self) -> dict:
        """Get cache statistics."""
        with self.lock:
            return {
                "size": len(self.cache),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl_seconds,
                "hit_rate": getattr(self, '_hit_count', 0) / max(getattr(self, '_total_requests', 1), 1)
            }


# Global cache instance
tile_cache = TileCache(max_size=1000, ttl_seconds=3600)