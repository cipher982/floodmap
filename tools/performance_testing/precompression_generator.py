#!/usr/bin/env python3
"""
Pre-compression tile generation for A/B performance testing.

Generates pre-compressed tile variants for the performance testing framework:
- Raw .u16 files (uint16 binary)
- Brotli compressed .u16.br files
- Gzip compressed .u16.gz files

This allows testing pre-compressed file serving vs runtime compression.
"""

import os
import sys
import json
import gzip
import math
import zstandard as zstd
import numpy as np
from pathlib import Path
from typing import Optional, Tuple, Set
import argparse
import logging

try:
    import brotli
except ImportError:
    print("Warning: brotli not available, .br files will be skipped")
    brotli = None

# Add src to path to import elevation loader
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "api"))

from elevation_loader import elevation_loader
from config import ELEVATION_DATA_DIR, TILE_SIZE, NODATA_VALUE

logger = logging.getLogger(__name__)


class PrecompressionGenerator:
    """Generate pre-compressed tile files for performance testing."""
    
    def __init__(self, source_dir: Path, output_dir: Path):
        self.source_dir = source_dir
        self.output_dir = output_dir
        self.tile_size = TILE_SIZE
        self.elevation_loader = elevation_loader
        
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
    
    def generate_tile_data(self, z: int, x: int, y: int) -> Optional[bytes]:
        """Generate raw elevation data as Uint16 array - matches production logic."""
        try:
            # Use the same logic as production tiles_v1.py:generate_elevation_data_sync
            elevation_data = self.elevation_loader.get_elevation_for_tile(x, y, z, tile_size=self.tile_size)
            
            if elevation_data is None:
                # Return empty elevation data
                empty_data = np.full((self.tile_size, self.tile_size), 65535, dtype=np.uint16)
                return empty_data.tobytes()
            
            # Convert elevation to uint16 format
            # Range: -500m to 9000m → 0 to 65534
            # Special value: 65535 = NODATA
            normalized = np.zeros_like(elevation_data, dtype=np.float32)
            
            # Handle NODATA values
            nodata_mask = (elevation_data == NODATA_VALUE) | (elevation_data < -500) | (elevation_data > 9000)
            valid_mask = ~nodata_mask
            
            # Normalize valid elevations to 0-65534 range
            normalized[valid_mask] = np.clip(
                (elevation_data[valid_mask] + 500) / 9500 * 65534, 
                0, 
                65534
            )
            normalized[nodata_mask] = 65535
            
            # Convert to uint16
            uint16_data = normalized.astype(np.uint16)
            
            return uint16_data.tobytes()
            
        except Exception as e:
            logger.error(f"Error generating tile data for {z}/{x}/{y}: {e}")
            # Return empty elevation data on error
            empty_data = np.full((self.tile_size, self.tile_size), 65535, dtype=np.uint16)
            return empty_data.tobytes()
    
    def generate_sample_tiles(self, zoom_levels: list[int] = [10, 12, 14], 
                            tiles_per_zoom: int = 5) -> Set[Tuple[int, int, int]]:
        """Generate a representative sample of tiles for testing.
        
        Returns set of (z, x, y) tuples for tiles that were generated.
        """
        generated_tiles = set()
        
        # Sample coordinates from different US regions for diversity
        sample_locations = [
            (40.7128, -74.0060),  # NYC
            (34.0522, -118.2437), # LA  
            (41.8781, -87.6298),  # Chicago
            (29.7604, -95.3698),  # Houston
            (25.7617, -80.1918),  # Miami
        ]
        
        for zoom in zoom_levels:
            logger.info(f"Generating sample tiles for zoom level {zoom}")
            tiles_generated = 0
            
            for lat, lon in sample_locations:
                if tiles_generated >= tiles_per_zoom:
                    break
                    
                x, y = self.deg2num(lat, lon, zoom)
                
                # Check if we have elevation data for this tile
                lat_top, lat_bottom, lon_left, lon_right = self.num2deg(x, y, zoom)
                overlapping_files = self.elevation_loader.find_elevation_files_for_tile(
                    lat_top, lat_bottom, lon_left, lon_right
                )
                
                if overlapping_files:
                    tile_data = self.generate_tile_data(zoom, x, y)
                    if tile_data and len(tile_data) > 0:
                        self.save_tile_variants(zoom, x, y, tile_data)
                        generated_tiles.add((zoom, x, y))
                        tiles_generated += 1
                        logger.info(f"Generated tile {zoom}/{x}/{y} ({len(tile_data)} bytes)")
        
        return generated_tiles
    
    def save_tile_variants(self, z: int, x: int, y: int, tile_data: bytes):
        """Save tile in all compression variants."""
        # Create directory structure
        tile_dir = self.output_dir / f"{z}" / f"{x}"
        tile_dir.mkdir(parents=True, exist_ok=True)
        
        base_path = tile_dir / f"{y}"
        
        # Save raw .u16 file
        with open(f"{base_path}.u16", 'wb') as f:
            f.write(tile_data)
        
        # Save brotli compressed variant
        if brotli:
            compressed_br = brotli.compress(tile_data, quality=1)
            with open(f"{base_path}.u16.br", 'wb') as f:
                f.write(compressed_br)
            logger.debug(f"Brotli: {len(tile_data)} → {len(compressed_br)} bytes ({len(compressed_br)/len(tile_data)*100:.1f}%)")
        
        # Save gzip compressed variant  
        compressed_gz = gzip.compress(tile_data, compresslevel=1)
        with open(f"{base_path}.u16.gz", 'wb') as f:
            f.write(compressed_gz)
        logger.debug(f"Gzip: {len(tile_data)} → {len(compressed_gz)} bytes ({len(compressed_gz)/len(tile_data)*100:.1f}%)")
    
    def generate_manifest(self, generated_tiles: Set[Tuple[int, int, int]]):
        """Generate manifest file listing all pre-compressed tiles."""
        manifest = {
            "generated_at": "2025-01-01T00:00:00Z",  # Will be updated when run
            "tile_count": len(generated_tiles),
            "compression_variants": ["raw", "br", "gz"],
            "tiles": sorted(list(generated_tiles))
        }
        
        manifest_path = self.output_dir / "manifest.json"
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        
        logger.info(f"Generated manifest with {len(generated_tiles)} tiles: {manifest_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate pre-compressed tiles for performance testing")
    parser.add_argument("--source-dir", type=Path, default=ELEVATION_DATA_DIR,
                       help="Source directory containing .zst elevation files")
    parser.add_argument("--output-dir", type=Path, default=Path("tools/performance_testing/precompressed_tiles"),
                       help="Output directory for pre-compressed tiles")
    parser.add_argument("--zoom-levels", type=int, nargs="+", default=[10, 12, 14],
                       help="Zoom levels to generate tiles for")
    parser.add_argument("--tiles-per-zoom", type=int, default=5,
                       help="Number of tiles to generate per zoom level")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Enable verbose logging")
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format='%(levelname)s: %(message)s')
    
    # Validate source directory
    if not args.source_dir.exists():
        logger.error(f"Source directory does not exist: {args.source_dir}")
        sys.exit(1)
    
    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate pre-compressed tiles
    generator = PrecompressionGenerator(args.source_dir, args.output_dir)
    generated_tiles = generator.generate_sample_tiles(args.zoom_levels, args.tiles_per_zoom)
    generator.generate_manifest(generated_tiles)
    
    logger.info(f"Pre-compression complete! Generated {len(generated_tiles)} tiles in {args.output_dir}")


if __name__ == "__main__":
    main()