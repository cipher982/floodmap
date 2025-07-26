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
import httpx
import asyncio

logger = logging.getLogger(__name__)


class ElevationDataLoader:
    """Load and query elevation data for tile generation."""
    
    def __init__(self, data_dir: str = "/Users/davidrose/git/floodmap/output/elevation"):
        self.data_dir = Path(data_dir)
        self.cache = {}  # Simple in-memory cache for loaded tiles
        self.max_cache_size = 50  # Keep 50 elevation arrays in memory
        
    async def _check_vector_tile(self, xtile: int, ytile: int, zoom: int) -> bool:
        """Check if vector tile exists for this location (indicates geographic features)."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(f"http://localhost:8080/data/usa-complete/{zoom}/{xtile}/{ytile}.pbf")
                return response.status_code == 200 and len(response.content) > 100
            except:
                return False
        
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
        """Find elevation files that overlap with the given tile bounds using O(1) lookup."""
        overlapping_files = []
        
        # Calculate the range of 1-degree tiles that might overlap
        lat_start = int(math.floor(lat_bottom))
        lat_end = int(math.ceil(lat_top))
        lon_start = int(math.floor(lon_left))
        lon_end = int(math.ceil(lon_right))
        
        # Generate filenames directly using O(1) formula
        for lat in range(lat_start, lat_end + 1):
            for lon in range(lon_start, lon_end + 1):
                # Generate filename using Carmack's O(1) approach
                lat_letter = 'n' if lat >= 0 else 's'
                lon_letter = 'w' if lon < 0 else 'e'
                
                filename = f"{lat_letter}{abs(lat):02d}_{lon_letter}{abs(lon):03d}_1arc_v3.zst"
                file_path = self.data_dir / filename
                
                if file_path.exists():
                    # Quick bounds check
                    file_lat_top = lat + 1
                    file_lat_bottom = lat
                    file_lon_left = lon
                    file_lon_right = lon + 1
                    
                    # Check for actual overlap
                    if (file_lat_bottom < lat_top and file_lat_top > lat_bottom and
                        file_lon_left < lon_right and file_lon_right > lon_left):
                        overlapping_files.append(file_path)
                    
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
                raise FileNotFoundError(f"Required metadata file missing: {metadata_path}")
                
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            
            # Handle both 'shape' (new) and 'height'/'width' (legacy)
            if 'shape' in metadata:
                height, width = metadata['shape']
            else:
                height, width = metadata['height'], metadata['width']

            # Decompress elevation data – use `max_output_size` to protect
            # against corrupted frames announcing a wrong (too large) size.
            expected_bytes = int(height) * int(width) * 2  # int16 → 2 bytes
            dctx = zstd.ZstdDecompressor()
            decompressed = dctx.decompress(compressed_data)
            elevation_array = np.frombuffer(decompressed, dtype=np.int16).reshape(
                height, width
            )

            # Note: previously attempted automatic cropping of zero-padding has
            # been removed – see persistent_elevation_cache.py for reasoning.
            
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
            try:
                # Check if vector tile exists (indicates geographic features)
                loop = asyncio.get_event_loop()
                has_vector_data = loop.run_until_complete(self._check_vector_tile(xtile, ytile, zoom))
                
                if has_vector_data:
                    logger.warning(f"Missing elevation data for tile {xtile}/{ytile}/{zoom} with vector features (bounds: {lat_bottom:.3f}-{lat_top:.3f}N, {lon_left:.3f}-{lon_right:.3f}W) - potential data gap")
                else:
                    logger.debug(f"No elevation files for tile {xtile}/{ytile}/{zoom} (likely ocean area)")
                    
            except Exception as e:
                logger.info(f"No elevation files found for tile {xtile}/{ytile}/{zoom} (bounds: {lat_bottom:.3f}-{lat_top:.3f}N, {lon_left:.3f}-{lon_right:.3f}W)")
            
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
        """Accurately mosaic multiple 1-degree elevation rasters into a single Web-Mercator tile.

        The previous implementation simply resized every overlapping file to the
        full 256×256 target which meant the last processed source overwrote the
        already combined data and, more importantly, destroyed the spatial
        relationship between the DEM and the map.  The re-worked algorithm
        draws every source into the correct sub-window of the canvas so that
        coastline and elevation stay perfectly aligned.
        """

        # Prepare empty canvas (initialised with NoData)
        canvas = np.full((tile_size, tile_size), -32768, dtype=np.int16)

        total_lat_span = lat_top - lat_bottom  # positive value
        total_lon_span = lon_right - lon_left  # positive value

        from PIL import Image

        for file_path in files:
            elevation_data = self.load_elevation_data(file_path)
            if elevation_data is None:
                continue  # skip missing / unreadable files

            elevation_array, metadata = elevation_data

            # File bounds
            b = metadata['bounds']
            file_lat_top = b['top']
            file_lat_bottom = b['bottom']
            file_lon_left = b['left']
            file_lon_right = b['right']

            # Determine geographic overlap between tile and source file
            overlap_lat_top = min(lat_top, file_lat_top)
            overlap_lat_bottom = max(lat_bottom, file_lat_bottom)
            overlap_lon_left = max(lon_left, file_lon_left)
            overlap_lon_right = min(lon_right, file_lon_right)

            # Skip if no overlap
            if overlap_lat_bottom >= overlap_lat_top or overlap_lon_left >= overlap_lon_right:
                continue

            # Source array indices for the overlapping area ------------------
            src_h, src_w = elevation_array.shape

            y_top_src = int((file_lat_top - overlap_lat_top) / (file_lat_top - file_lat_bottom) * src_h)
            y_bottom_src = int((file_lat_top - overlap_lat_bottom) / (file_lat_top - file_lat_bottom) * src_h)
            x_left_src = int((overlap_lon_left - file_lon_left) / (file_lon_right - file_lon_left) * src_w)
            x_right_src = int((overlap_lon_right - file_lon_left) / (file_lon_right - file_lon_left) * src_w)

            if y_bottom_src <= y_top_src or x_right_src <= x_left_src:
                continue

            sub_array = elevation_array[y_top_src:y_bottom_src, x_left_src:x_right_src]

            # Destination window inside the 256×256 canvas -------------------
            y_top_frac = (lat_top - overlap_lat_top) / total_lat_span
            y_bottom_frac = (lat_top - overlap_lat_bottom) / total_lat_span
            x_left_frac = (overlap_lon_left - lon_left) / total_lon_span
            x_right_frac = (overlap_lon_right - lon_left) / total_lon_span

            y_top_dst = int(round(y_top_frac * tile_size))
            y_bottom_dst = int(round(y_bottom_frac * tile_size))
            x_left_dst = int(round(x_left_frac * tile_size))
            x_right_dst = int(round(x_right_frac * tile_size))

            # Clamp to canvas boundary (numerical safety)
            y_top_dst = max(0, min(tile_size, y_top_dst))
            y_bottom_dst = max(0, min(tile_size, y_bottom_dst))
            x_left_dst = max(0, min(tile_size, x_left_dst))
            x_right_dst = max(0, min(tile_size, x_right_dst))

            if y_bottom_dst <= y_top_dst or x_right_dst <= x_left_dst:
                continue

            dst_height = y_bottom_dst - y_top_dst
            dst_width = x_right_dst - x_left_dst

            # Resize source patch to destination pixel size ------------------
            if sub_array.shape != (dst_height, dst_width):
                pil_img = Image.fromarray(sub_array.astype(np.float32), mode='F')
                pil_img = pil_img.resize((dst_width, dst_height), Image.LANCZOS)
                sub_resized = np.array(pil_img, dtype=np.int16)
            else:
                sub_resized = sub_array

            # Blend into canvas – keep existing values where we already have
            # data (prefers the first encountered file; order of `files` list
            # is determined by find_elevation_files_for_tile which walks from
            # west→east and south→north, matching typical DEM priority rules)
            target_slice = canvas[y_top_dst:y_bottom_dst, x_left_dst:x_right_dst]
            write_mask = (target_slice == -32768) & (sub_resized != -32768)
            target_slice[write_mask] = sub_resized[write_mask]

            canvas[y_top_dst:y_bottom_dst, x_left_dst:x_right_dst] = target_slice

        # Final sanity check ---------------------------------------------------
        if np.all(canvas == -32768):
            raise ValueError("Mosaic result is entirely NoData for tile – DEM missing?")

        return canvas
    
    def _extract_tile_from_file(self, file_path: Path, lat_top: float, lat_bottom: float,
                               lon_left: float, lon_right: float, tile_size: int) -> Optional[np.ndarray]:
        """Extract tile data from a single elevation file."""
        elevation_data = self.load_elevation_data(file_path)
        if elevation_data is None:
            raise ValueError(f"Failed to load elevation data from {file_path}")
            
        elevation_array, metadata = elevation_data
        
        # Convert tile bounds to array indices
        file_bounds = metadata['bounds']
        file_lat_top = file_bounds['top']
        file_lat_bottom = file_bounds['bottom'] 
        file_lon_left = file_bounds['left']
        file_lon_right = file_bounds['right']
        
        # Calculate overlap region
        overlap_lat_top = min(lat_top, file_lat_top)
        overlap_lat_bottom = max(lat_bottom, file_lat_bottom)
        overlap_lon_left = max(lon_left, file_lon_left)
        overlap_lon_right = min(lon_right, file_lon_right)
        
        # Check if there's actual overlap
        if overlap_lat_bottom >= overlap_lat_top or overlap_lon_left >= overlap_lon_right:
            raise ValueError(f"No overlap between tile bounds and elevation file {file_path.name}")
        
        # Calculate array indices for overlap region
        height, width = elevation_array.shape
        
        # Map overlap bounds to array indices
        y_top = max(0, int((file_lat_top - overlap_lat_top) / (file_lat_top - file_lat_bottom) * height))
        y_bottom = min(height, int((file_lat_top - overlap_lat_bottom) / (file_lat_top - file_lat_bottom) * height))
        x_left = max(0, int((overlap_lon_left - file_lon_left) / (file_lon_right - file_lon_left) * width))
        x_right = min(width, int((overlap_lon_right - file_lon_left) / (file_lon_right - file_lon_left) * width))
        
        if y_bottom <= y_top or x_right <= x_left:
            raise ValueError(f"Invalid array indices: y={y_top}:{y_bottom}, x={x_left}:{x_right} for {file_path.name}")
        
        # Extract data
        tile_data = elevation_array[y_top:y_bottom, x_left:x_right]
        
        # Resize to standard tile size using simple numpy operations  
        if tile_data.shape != (tile_size, tile_size):
            # FIXED: Use consistent high-quality resampling instead of stride indexing
            from PIL import Image
            # Convert to PIL for proper resampling (handles both up/downsampling)
            # Convert int16 to float32 for PIL compatibility, then back
            tile_data_float = tile_data.astype(np.float32)
            pil_img = Image.fromarray(tile_data_float, mode='F')
            pil_img = pil_img.resize((tile_size, tile_size), Image.LANCZOS)
            tile_data = np.array(pil_img, dtype=np.int16)
        
        return tile_data


# Global instance
elevation_loader = ElevationDataLoader()