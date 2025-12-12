"""
Unit tests for tile_cache.py - LRU tile caching logic.
"""

import threading
import time

import pytest

# Import the module under test
from tile_cache import CacheEntry, TileCache


class TestCacheEntry:
    """Test the CacheEntry dataclass."""

    def test_cache_entry_creation(self):
        """CacheEntry should store tile data, timestamp, and water level."""
        data = b"test tile data"
        timestamp = time.time()
        water_level = 2.5

        entry = CacheEntry(tile_data=data, timestamp=timestamp, water_level=water_level)

        assert entry.tile_data == data
        assert entry.timestamp == timestamp
        assert entry.water_level == water_level


class TestTileCache:
    """Test suite for TileCache class."""

    @pytest.fixture
    def cache(self):
        """Create a fresh cache instance for each test."""
        return TileCache(max_size=10, ttl_seconds=60)

    @pytest.fixture
    def small_cache(self):
        """Create a small cache for LRU eviction tests."""
        return TileCache(max_size=3, ttl_seconds=60)

    # ============== Basic Operations ==============

    def test_put_and_get(self, cache):
        """Basic put/get should work."""
        cache.put(2.0, 10, 100, 200, b"tile_data")
        result = cache.get(2.0, 10, 100, 200)
        assert result == b"tile_data"

    def test_get_missing_key(self, cache):
        """Getting a non-existent key should return None."""
        result = cache.get(2.0, 10, 100, 200)
        assert result is None

    def test_put_overwrites_existing(self, cache):
        """Putting with same key should overwrite."""
        cache.put(2.0, 10, 100, 200, b"old_data")
        cache.put(2.0, 10, 100, 200, b"new_data")
        result = cache.get(2.0, 10, 100, 200)
        assert result == b"new_data"

    def test_exists(self, cache):
        """exists() should return True for cached tiles."""
        assert not cache.exists(2.0, 10, 100, 200)
        cache.put(2.0, 10, 100, 200, b"data")
        assert cache.exists(2.0, 10, 100, 200)

    def test_clear(self, cache):
        """clear() should remove all entries."""
        cache.put(2.0, 10, 100, 200, b"data1")
        cache.put(3.0, 11, 101, 201, b"data2")
        assert len(cache.cache) == 2

        cache.clear()
        assert len(cache.cache) == 0
        assert cache.get(2.0, 10, 100, 200) is None

    # ============== Water Level Clustering ==============

    def test_cluster_water_level(self, cache):
        """Water levels should be clustered to 0.1m increments."""
        assert cache._cluster_water_level(2.04) == 2.0
        # Python's round() uses banker's rounding, so 2.05 rounds to 2.0
        assert cache._cluster_water_level(2.05) in [
            2.0,
            2.1,
        ]  # Allow for banker's rounding
        assert cache._cluster_water_level(2.06) == 2.1
        assert cache._cluster_water_level(0.0) == 0.0
        assert cache._cluster_water_level(-1.23) == -1.2

    def test_similar_water_levels_share_cache(self, cache):
        """Similar water levels should hit the same cache entry."""
        cache.put(2.02, 10, 100, 200, b"data")
        # 2.03 clusters to same value as 2.02 (both -> 2.0)
        result = cache.get(2.03, 10, 100, 200)
        assert result == b"data"

    def test_different_water_levels_separate_cache(self, cache):
        """Different water levels should have separate cache entries."""
        cache.put(2.0, 10, 100, 200, b"data_2m")
        cache.put(3.0, 10, 100, 200, b"data_3m")

        assert cache.get(2.0, 10, 100, 200) == b"data_2m"
        assert cache.get(3.0, 10, 100, 200) == b"data_3m"

    # ============== String Cache Key Format ==============

    def test_string_cache_key_prefix(self, cache):
        """Should support string cache key prefixes (new format)."""
        cache.put("2.0_PNG", 10, 100, 200, b"png_data")
        result = cache.get("2.0_PNG", 10, 100, 200)
        assert result == b"png_data"

    def test_string_and_float_keys_separate(self, cache):
        """String and float keys should produce separate entries."""
        cache.put(2.0, 10, 100, 200, b"float_data")
        cache.put("2.0_PNG", 10, 100, 200, b"string_data")

        # Both should be retrievable with their original key types
        assert cache.get(2.0, 10, 100, 200) == b"float_data"
        assert cache.get("2.0_PNG", 10, 100, 200) == b"string_data"

    def test_special_cache_keys(self, cache):
        """Special keys like -888.0 should work."""
        cache.put("-888.0", 10, 100, 200, b"special_data")
        result = cache.get("-888.0", 10, 100, 200)
        assert result == b"special_data"

    # ============== LRU Eviction ==============

    def test_lru_eviction_when_full(self, small_cache):
        """Oldest entries should be evicted when cache is full."""
        # Fill the cache
        small_cache.put(1.0, 10, 1, 1, b"first")
        small_cache.put(2.0, 10, 2, 2, b"second")
        small_cache.put(3.0, 10, 3, 3, b"third")

        # Cache is now full (3 entries)
        assert len(small_cache.cache) == 3

        # Add one more - should evict "first"
        small_cache.put(4.0, 10, 4, 4, b"fourth")

        assert len(small_cache.cache) == 3
        assert small_cache.get(1.0, 10, 1, 1) is None  # Evicted
        assert small_cache.get(2.0, 10, 2, 2) == b"second"  # Still there
        assert small_cache.get(4.0, 10, 4, 4) == b"fourth"  # New entry

    def test_lru_access_updates_order(self, small_cache):
        """Accessing an entry should move it to the end of LRU order."""
        small_cache.put(1.0, 10, 1, 1, b"first")
        small_cache.put(2.0, 10, 2, 2, b"second")
        small_cache.put(3.0, 10, 3, 3, b"third")

        # Access "first" to move it to end
        small_cache.get(1.0, 10, 1, 1)

        # Add new entry - should evict "second" (oldest now)
        small_cache.put(4.0, 10, 4, 4, b"fourth")

        assert small_cache.get(1.0, 10, 1, 1) == b"first"  # Still there
        assert small_cache.get(2.0, 10, 2, 2) is None  # Evicted

    # ============== TTL Expiration ==============

    def test_ttl_expiration(self):
        """Entries should expire after TTL."""
        cache = TileCache(max_size=10, ttl_seconds=0.1)  # 100ms TTL
        cache.put(2.0, 10, 100, 200, b"data")

        # Should exist immediately
        assert cache.get(2.0, 10, 100, 200) == b"data"

        # Wait for expiration
        time.sleep(0.15)

        # Should be expired now
        assert cache.get(2.0, 10, 100, 200) is None

    def test_ttl_expiration_via_exists(self):
        """exists() should also check TTL."""
        cache = TileCache(max_size=10, ttl_seconds=0.1)
        cache.put(2.0, 10, 100, 200, b"data")

        assert cache.exists(2.0, 10, 100, 200)

        time.sleep(0.15)

        assert not cache.exists(2.0, 10, 100, 200)

    def test_infinite_ttl(self):
        """None or inf TTL should never expire."""
        cache = TileCache(max_size=10, ttl_seconds=None)
        cache.put(2.0, 10, 100, 200, b"data")

        # Should still exist (infinity check is a bit silly but validates logic)
        assert cache.get(2.0, 10, 100, 200) == b"data"

    # ============== Statistics ==============

    def test_stats_hit_miss(self, cache):
        """Stats should track hits and misses."""
        # Initial state
        stats = cache.stats()
        assert stats["hit_count"] == 0
        assert stats["miss_count"] == 0

        # Miss
        cache.get(2.0, 10, 100, 200)
        stats = cache.stats()
        assert stats["miss_count"] == 1
        assert stats["hit_count"] == 0

        # Put + Hit
        cache.put(2.0, 10, 100, 200, b"data")
        cache.get(2.0, 10, 100, 200)
        stats = cache.stats()
        assert stats["hit_count"] == 1
        assert stats["miss_count"] == 1

    def test_stats_hit_rate(self, cache):
        """Hit rate calculation should be correct."""
        cache.put(2.0, 10, 100, 200, b"data")

        # 3 hits
        for _ in range(3):
            cache.get(2.0, 10, 100, 200)

        # 1 miss
        cache.get(3.0, 10, 100, 200)

        stats = cache.stats()
        assert stats["total_requests"] == 4
        assert stats["hit_rate"] == 0.75

    def test_stats_size(self, cache):
        """Stats should report current cache size."""
        assert cache.stats()["size"] == 0

        cache.put(1.0, 10, 1, 1, b"a")
        cache.put(2.0, 10, 2, 2, b"b")

        stats = cache.stats()
        assert stats["size"] == 2
        assert stats["max_size"] == 10

    # ============== Thread Safety ==============

    def test_concurrent_access(self, cache):
        """Cache should be thread-safe under concurrent access."""
        errors = []

        def writer():
            try:
                for i in range(100):
                    cache.put(float(i % 10), 10, i, i, f"data_{i}".encode())
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(100):
                    cache.get(float(i % 10), 10, i, i)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread errors: {errors}"

    def test_concurrent_stats(self, cache):
        """Stats should be accurate under concurrent access."""
        num_ops = 100

        def worker():
            for i in range(num_ops):
                cache.put(float(i), 10, i, i, b"data")
                cache.get(float(i), 10, i, i)

        threads = [threading.Thread(target=worker) for _ in range(4)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        stats = cache.stats()
        # Each worker does 100 puts and 100 gets (all hits)
        assert stats["total_requests"] >= num_ops * 4


class TestCacheKeyGeneration:
    """Test cache key generation edge cases."""

    @pytest.fixture
    def cache(self):
        return TileCache(max_size=100, ttl_seconds=60)

    def test_different_coordinates_different_keys(self, cache):
        """Different coordinates should produce different cache entries."""
        cache.put(2.0, 10, 100, 200, b"tile1")
        cache.put(2.0, 10, 101, 200, b"tile2")
        cache.put(2.0, 10, 100, 201, b"tile3")
        cache.put(2.0, 11, 100, 200, b"tile4")

        assert cache.get(2.0, 10, 100, 200) == b"tile1"
        assert cache.get(2.0, 10, 101, 200) == b"tile2"
        assert cache.get(2.0, 10, 100, 201) == b"tile3"
        assert cache.get(2.0, 11, 100, 200) == b"tile4"

    def test_zero_coordinates(self, cache):
        """Zero coordinates should work correctly."""
        cache.put(0.0, 0, 0, 0, b"origin_tile")
        result = cache.get(0.0, 0, 0, 0)
        assert result == b"origin_tile"

    def test_large_coordinates(self, cache):
        """Large coordinates (high zoom levels) should work."""
        # Zoom 18 can have coordinates up to 2^18 = 262144
        cache.put(2.0, 18, 200000, 200000, b"high_zoom_tile")
        result = cache.get(2.0, 18, 200000, 200000)
        assert result == b"high_zoom_tile"
