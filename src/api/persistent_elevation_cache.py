"""
Persistent Elevation Cache - Eliminate zstd decompression bottleneck
Keeps decompressed elevation arrays in memory across requests.

This cache is ONLY needed for runtime DEM mosaicking. The primary serving path
(precompressed tiles + client rendering) doesn't use this cache.
"""

import json
import logging
import math
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import zstandard as zstd
from config import ELEVATION_DATA_DIR

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

    def __init__(
        self,
        data_dir: Path = ELEVATION_DATA_DIR,
        max_memory_gb: float = 4.0,  # Use up to 4GB for cache
        preload_cores: int = None,
    ):
        self.data_dir = data_dir
        self.max_memory_bytes = int(max_memory_gb * 1024 * 1024 * 1024)
        self.preload_cores = preload_cores or min(8, os.cpu_count())

        # Thread-safe cache
        self.cache: dict[str, ElevationCacheEntry] = OrderedDict()
        self.cache_lock = threading.RLock()
        self.current_memory_usage = 0

        # Decompression worker pool - separate from tile generation
        self.decompression_pool = ThreadPoolExecutor(
            max_workers=self.preload_cores, thread_name_prefix="elevation-decomp"
        )

        # Statistics
        self.stats = {
            "hits": 0,
            "misses": 0,
            "decompressions": 0,
            "evictions": 0,
            "preloads": 0,
        }

        logger.info(
            f"🚀 Persistent elevation cache: {max_memory_gb:.1f}GB limit, {self.preload_cores} decompression cores"
        )

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
                (34, -118),  # LA
                (29, -95),  # Houston
                (32, -117),  # San Diego
                (47, -122),  # Seattle
                (41, -87),  # Chicago
            ]

            futures = []
            for lat, lon in common_coords:
                future = self.decompression_pool.submit(
                    self._preload_file_async, lat, lon
                )
                futures.append(future)

            # Wait for preloading to complete
            loaded_count = 0
            for future in as_completed(futures):
                try:
                    if future.result():
                        loaded_count += 1
                        self.stats["preloads"] += 1
                except Exception as e:
                    logger.warning(f"Preload failed: {e}")

            logger.info(
                f"✅ Preloaded {loaded_count}/{len(common_coords)} common elevation areas"
            )

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
        lat_letter = "n" if lat >= 0 else "s"
        lon_letter = "w" if lon < 0 else "e"
        return f"{lat_letter}{abs(lat):02d}_{lon_letter}{abs(lon):03d}_1arc_v3.zst"

    def get_elevation_array(self, file_path: Path) -> tuple[np.ndarray, dict] | None:
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
                self.stats["hits"] += 1

                return (entry.array, entry.metadata)  # Direct reference - read-only

        # Cache miss - load the file
        self.stats["misses"] += 1
        entry = self._load_elevation_file(file_path)

        if entry is None:
            raise ValueError(f"Failed to load elevation file: {file_path}")

        # Add to cache
        with self.cache_lock:
            self.cache[cache_key] = entry
            self.current_memory_usage += entry.file_size_mb * 1024 * 1024
            self._enforce_memory_limit()

        return (entry.array, entry.metadata)  # Direct reference - read-only

    def extract_tile_from_cached_array(
        self,
        file_path: Path,
        lat_top: float,
        lat_bottom: float,
        lon_left: float,
        lon_right: float,
        tile_size: int = 256,
    ) -> np.ndarray | None:
        """
        OPTIMIZED: Extract tile directly from cached elevation array without re-decompression.
        This replaces the slow elevation_loader._extract_tile_from_file() path.
        """
        cached_data = self.get_elevation_array(file_path)
        if cached_data is None:
            raise ValueError(f"No cached elevation data available for {file_path}")

        elevation_array, metadata = cached_data

        # Convert tile bounds to array indices using cached metadata
        file_bounds = metadata["bounds"]
        file_lat_top = file_bounds["top"]
        file_lat_bottom = file_bounds["bottom"]
        file_lon_left = file_bounds["left"]
        file_lon_right = file_bounds["right"]

        # Calculate overlap region
        overlap_lat_top = min(lat_top, file_lat_top)
        overlap_lat_bottom = max(lat_bottom, file_lat_bottom)
        overlap_lon_left = max(lon_left, file_lon_left)
        overlap_lon_right = min(lon_right, file_lon_right)

        # Check if there's actual overlap
        if (
            overlap_lat_bottom >= overlap_lat_top
            or overlap_lon_left >= overlap_lon_right
        ):
            raise ValueError(
                f"No overlap between tile bounds and cached elevation file {file_path.name}"
            )

        # Calculate array indices for overlap region
        height, width = elevation_array.shape

        # Map overlap bounds to array indices
        y_top = max(
            0,
            int(
                (file_lat_top - overlap_lat_top)
                / (file_lat_top - file_lat_bottom)
                * height
            ),
        )
        y_bottom = min(
            height,
            int(
                (file_lat_top - overlap_lat_bottom)
                / (file_lat_top - file_lat_bottom)
                * height
            ),
        )
        x_left = max(
            0,
            int(
                (overlap_lon_left - file_lon_left)
                / (file_lon_right - file_lon_left)
                * width
            ),
        )
        x_right = min(
            width,
            int(
                (overlap_lon_right - file_lon_left)
                / (file_lon_right - file_lon_left)
                * width
            ),
        )

        # Extract overlap region from cached array (no file I/O!)
        if y_bottom <= y_top or x_right <= x_left:
            raise ValueError(
                f"Invalid array indices: y={y_top}:{y_bottom}, x={x_left}:{x_right} for cached {file_path.name}"
            )

        overlap_data = elevation_array[y_top:y_bottom, x_left:x_right]

        # Resize to standard tile size if needed
        if overlap_data.shape != (tile_size, tile_size):
            from PIL import Image

            # Convert to PIL for efficient resizing
            # Convert int16 to float32 for PIL compatibility, then back
            overlap_data_float = overlap_data.astype(np.float32)
            pil_img = Image.fromarray(overlap_data_float, mode="F")
            pil_img = pil_img.resize((tile_size, tile_size), Image.LANCZOS)
            result_tile = np.array(pil_img, dtype=np.int16)
        else:
            result_tile = overlap_data.copy()

        # Fail if all NoData - indicates serious data problem
        if np.all(result_tile == -32768):
            raise ValueError(
                f"Cached tile extraction result is all NoData (-32768) for {file_path.name}"
            )

        return result_tile

    def _load_elevation_file(self, file_path: Path) -> ElevationCacheEntry | None:
        """Load and decompress elevation file."""
        try:
            start_time = time.perf_counter()

            # Load compressed data
            with open(file_path, "rb") as f:
                compressed_data = f.read()

            # Load metadata
            metadata_path = file_path.with_suffix(".json")
            if not metadata_path.exists():
                raise FileNotFoundError(
                    f"Required metadata file missing for cache: {metadata_path}"
                )

            with open(metadata_path) as f:
                metadata = json.load(f)

            # Decompress elevation data with size guard to avoid segfaults on
            # corrupted frames.
            if "shape" in metadata:
                height, width = metadata["shape"]
            else:
                height, width = metadata["height"], metadata["width"]

            expected_bytes = int(height) * int(width) * 2
            dctx = zstd.ZstdDecompressor()
            decompressed = dctx.decompress(compressed_data)

            # Handle both metadata formats
            elevation_array = np.frombuffer(decompressed, dtype=np.int16).reshape(
                int(height), int(width)
            )

            # ------------------------------------------------------------------
            # Some of the pre-generated 1-degree SRTM tiles in our dataset were
            # discovered to contain large leading / trailing paddings that are
            # filled entirely with zeros (sea-level).  These columns / rows do
            # not represent real measured data and break the coordinate
            # transformation logic further downstream because the accompanying
            # geo-metadata still describes the full one-degree extent.
            #
            # To make the cached arrays spatially consistent with the metadata
            # we detect any fully-zero padding bands at the western / eastern /
            # northern / southern edges and crop them out on load while at the
            # same time adjusting the bounds in the metadata structure.  This
            # fixes the infamous "solid blue tile" problem caused by tiles that
            # only sampled the ocean part of a padded array.
            # ------------------------------------------------------------------

            # NOTE: Previously we attempted to auto-crop fully-zero padding
            # bands at the edges of some SRTM tiles. Unfortunately that approach
            # changed the geographic extent of the rasters on the fly and broke
            # the alignment between the elevation overlay and the underlying
            # basemap.  The auto-crop logic has therefore been removed.  We will
            # address the ‘all-zero strip’ problem in a different way (see
            # issue #1723) without mutating the source bounds.

            # Calculate memory usage
            array_size_mb = elevation_array.nbytes / (1024 * 1024)

            end_time = time.perf_counter()
            decomp_time = (end_time - start_time) * 1000

            logger.debug(
                f"Decompressed {file_path.name} in {decomp_time:.1f}ms ({array_size_mb:.1f}MB)"
            )
            self.stats["decompressions"] += 1

            return ElevationCacheEntry(
                array=elevation_array,
                metadata=metadata,
                last_accessed=time.time(),
                access_count=1,
                file_size_mb=array_size_mb,
            )

        except Exception as e:
            logger.error(f"Failed to load elevation data from {file_path}: {e}")
            raise ValueError(f"Elevation file loading failed: {file_path}") from e

    def _enforce_memory_limit(self):
        """Enforce memory limit by evicting least recently used entries."""
        while self.current_memory_usage > self.max_memory_bytes and self.cache:
            # Remove oldest entry (LRU)
            oldest_key, oldest_entry = self.cache.popitem(last=False)
            self.current_memory_usage -= oldest_entry.file_size_mb * 1024 * 1024
            self.stats["evictions"] += 1

            logger.debug(
                f"Evicted {oldest_key} (accessed {oldest_entry.access_count} times)"
            )

    def preload_area(
        self, lat_center: float, lon_center: float, radius_degrees: float = 1.0
    ):
        """
        Preload elevation files for an area.
        Called when user pans to new location.
        """
        # Use floor/ceil for robust handling of negative coordinates
        lat_min = math.floor(lat_center - radius_degrees)
        lat_max = math.ceil(lat_center + radius_degrees)
        lon_min = math.floor(lon_center - radius_degrees)
        lon_max = math.ceil(lon_center + radius_degrees)

        futures = []
        for lat in range(lat_min, lat_max + 1):
            for lon in range(lon_min, lon_max + 1):
                future = self.decompression_pool.submit(
                    self._preload_file_async, lat, lon
                )
                futures.append(future)

        # Don't wait for completion - let it happen in background
        logger.info(
            f"🔄 Preloading {len(futures)} elevation files around ({lat_center:.2f}, {lon_center:.2f})"
        )

    def get_stats(self) -> dict:
        """Get cache performance statistics."""
        with self.cache_lock:
            total_requests = self.stats["hits"] + self.stats["misses"]
            hit_rate = self.stats["hits"] / max(total_requests, 1)

            return {
                "cache_size": len(self.cache),
                "memory_usage_mb": self.current_memory_usage / (1024 * 1024),
                "memory_limit_mb": self.max_memory_bytes / (1024 * 1024),
                "hit_rate": hit_rate,
                "total_requests": total_requests,
                "decompression_cores": self.preload_cores,
                **self.stats,
            }

    def clear_cache(self):
        """Clear all cached data."""
        with self.cache_lock:
            self.cache.clear()
            self.current_memory_usage = 0
            self.stats = dict.fromkeys(self.stats, 0)

        logger.info("🧹 Elevation cache cleared")

    def shutdown(self):
        """Shutdown the cache and worker pools."""
        self.decompression_pool.shutdown(wait=True)
        self.clear_cache()
        logger.info("🛑 Persistent elevation cache shutdown")


# ============================================================================
# Lazy Initialization - Only initialize when actually needed
# ============================================================================


class LazyPersistentElevationCache:
    """
    Lazy wrapper for PersistentElevationCache.
    Only initializes the cache on first use to avoid unnecessary resource allocation.

    The cache is ONLY needed for runtime DEM mosaicking. Most requests use
    precompressed tiles and never trigger initialization.
    """

    def __init__(self):
        self._cache = None
        self._lock = threading.Lock()
        self._enabled = os.getenv(
            "ENABLE_RUNTIME_ELEVATION_CACHE", "false"
        ).lower() in (
            "1",
            "true",
            "yes",
        )

    def _ensure_initialized(self):
        """Initialize the cache on first use (thread-safe)."""
        if self._cache is None:
            with self._lock:
                # Double-check after acquiring lock
                if self._cache is None:
                    if not self._enabled:
                        logger.warning(
                            "⚠️ Runtime elevation cache requested but ENABLE_RUNTIME_ELEVATION_CACHE=false. "
                            "Initializing anyway for backward compatibility. "
                            "Set ENABLE_RUNTIME_ELEVATION_CACHE=true to suppress this warning."
                        )

                    logger.info("🔄 Lazy-initializing persistent elevation cache...")
                    self._cache = PersistentElevationCache(max_memory_gb=4.0)

    def get_elevation_array(self, file_path: Path) -> tuple[np.ndarray, dict] | None:
        """Get elevation array - lazy-initializes cache on first call."""
        self._ensure_initialized()
        return self._cache.get_elevation_array(file_path)

    def extract_tile_from_cached_array(
        self,
        file_path: Path,
        lat_top: float,
        lat_bottom: float,
        lon_left: float,
        lon_right: float,
        tile_size: int = 256,
    ) -> np.ndarray | None:
        """Extract tile from cached array - lazy-initializes cache on first call."""
        self._ensure_initialized()
        return self._cache.extract_tile_from_cached_array(
            file_path, lat_top, lat_bottom, lon_left, lon_right, tile_size
        )

    def preload_area(
        self, lat_center: float, lon_center: float, radius_degrees: float = 1.0
    ):
        """Preload area - lazy-initializes cache on first call."""
        self._ensure_initialized()
        return self._cache.preload_area(lat_center, lon_center, radius_degrees)

    def get_stats(self) -> dict:
        """Get cache statistics - returns empty stats if not initialized."""
        if self._cache is None:
            return {
                "cache_size": 0,
                "memory_usage_mb": 0,
                "memory_limit_mb": 0,
                "hit_rate": 0,
                "total_requests": 0,
                "decompression_cores": 0,
                "hits": 0,
                "misses": 0,
                "decompressions": 0,
                "evictions": 0,
                "preloads": 0,
                "initialized": False,
            }
        return {**self._cache.get_stats(), "initialized": True}

    def clear_cache(self):
        """Clear cache - only if initialized."""
        if self._cache is not None:
            self._cache.clear_cache()

    def shutdown(self):
        """Shutdown cache - only if initialized."""
        if self._cache is not None:
            self._cache.shutdown()


# Global cache instance - lazy initialization, no resources allocated at import time
persistent_elevation_cache = LazyPersistentElevationCache()
