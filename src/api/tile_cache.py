"""
Simple in-memory tile cache for performance optimization.
"""

import threading
import time
from dataclasses import dataclass

from config import IS_DEVELOPMENT, TILE_CACHE_TTL


@dataclass
class CacheEntry:
    """Single cache entry with timestamp."""

    tile_data: bytes
    timestamp: float
    water_level: float


class TileCache:
    """Simple LRU cache for generated tiles."""

    def __init__(self, max_size: int = 5000, ttl_seconds: int = None):
        self.max_size = max_size
        # Tiles are immutable - cache forever internally (None = infinity)
        self.ttl_seconds = ttl_seconds or float("inf")
        self.cache = {}
        self.access_order = []  # For LRU eviction
        self.lock = threading.RLock()
        self.hit_count = 0
        self.miss_count = 0

    def _cluster_water_level(self, water_level: float) -> float:
        """Cluster water levels to 0.1m increments for better cache hits."""
        return round(water_level * 10) / 10  # Round to nearest 0.1

    def _make_key(self, cache_key_prefix: str, z: int, x: int, y: int) -> str:
        """Create cache key from tile coordinates and cache key prefix (water_level_format or special key)."""
        return f"{cache_key_prefix}:{z}:{x}:{y}"

    def get(self, cache_key_prefix, z: int, x: int, y: int) -> bytes | None:
        """Get cached tile if available and not expired."""
        # Support both old format (float) and new format (string with format)
        if isinstance(cache_key_prefix, float):
            clustered_level = self._cluster_water_level(cache_key_prefix)
            key = f"{clustered_level:.2f}:{z}:{x}:{y}"
        else:
            key = self._make_key(cache_key_prefix, z, x, y)

        with self.lock:
            if key not in self.cache:
                self.miss_count += 1
                return None

            entry = self.cache[key]

            # Check if expired
            if time.time() - entry.timestamp > self.ttl_seconds:
                del self.cache[key]
                if key in self.access_order:
                    self.access_order.remove(key)
                self.miss_count += 1
                return None

            # Update access order for LRU
            if key in self.access_order:
                self.access_order.remove(key)
            self.access_order.append(key)

            self.hit_count += 1
            return entry.tile_data

    def put(self, cache_key_prefix, z: int, x: int, y: int, tile_data: bytes):
        """Cache generated tile."""
        # Support both old format (float) and new format (string with format)
        if isinstance(cache_key_prefix, float):
            clustered_level = self._cluster_water_level(cache_key_prefix)
            key = f"{clustered_level:.2f}:{z}:{x}:{y}"
            water_level = cache_key_prefix
        else:
            key = self._make_key(cache_key_prefix, z, x, y)
            # Extract water level from format like "2.0_PNG" or use special values
            if "_" in str(cache_key_prefix):
                water_level = float(cache_key_prefix.split("_")[0])
            else:
                water_level = float(
                    cache_key_prefix
                )  # Handle special keys like "-888.0"

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
                tile_data=tile_data, timestamp=time.time(), water_level=water_level
            )

            # Update access order
            if key in self.access_order:
                self.access_order.remove(key)
            self.access_order.append(key)

    def exists(self, cache_key_prefix, z: int, x: int, y: int) -> bool:
        """Check if tile exists in cache without retrieving it."""
        # Support both old format (float) and new format (string with format)
        if isinstance(cache_key_prefix, float):
            clustered_level = self._cluster_water_level(cache_key_prefix)
            key = f"{clustered_level:.2f}:{z}:{x}:{y}"
        else:
            key = self._make_key(cache_key_prefix, z, x, y)

        with self.lock:
            if key not in self.cache:
                return False

            entry = self.cache[key]

            # Check if expired
            if time.time() - entry.timestamp > self.ttl_seconds:
                del self.cache[key]
                if key in self.access_order:
                    self.access_order.remove(key)
                return False

            return True

    def clear(self):
        """Clear all cached tiles."""
        with self.lock:
            self.cache.clear()
            self.access_order.clear()

    def stats(self) -> dict:
        """Get cache statistics."""
        with self.lock:
            total_requests = self.hit_count + self.miss_count
            return {
                "size": len(self.cache),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl_seconds,
                "hit_count": self.hit_count,
                "miss_count": self.miss_count,
                "total_requests": total_requests,
                "hit_rate": self.hit_count / max(total_requests, 1),
            }


# Global cache instance - development friendly
cache_ttl = (
    60 if IS_DEVELOPMENT else TILE_CACHE_TTL
)  # 60 seconds in development, infinite in production
tile_cache = TileCache(max_size=5000, ttl_seconds=cache_ttl)
