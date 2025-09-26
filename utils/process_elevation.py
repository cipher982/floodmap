#!/usr/bin/env python3
"""
Elevation data processing pipeline.
Handles ingestion, processing, and deployment of elevation data for flood mapping.
"""

import argparse
import json
import logging
import math
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import rasterio
import zstandard as zstd
from PIL import Image
from tqdm import tqdm

# Configure logging
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/elevation_processing.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


class ElevationProcessor:
    """Production elevation data processing pipeline."""

    def __init__(self, data_dir: Path, output_dir: Path):
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        self.temp_dir = Path("temp/processing")

        # Ensure directories exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        Path("logs").mkdir(exist_ok=True)

    def ingest_compressed(self, region_id: str) -> Path | None:
        """Ingest compressed elevation data and convert to working format."""
        zst_file = self.data_dir / "compressed_data/usa" / f"{region_id}.zst"
        json_file = zst_file.with_suffix(".json")

        if not zst_file.exists() or not json_file.exists():
            logger.error(f"Missing data files for {region_id}")
            return None

        try:
            # Read metadata
            with open(json_file) as f:
                metadata = json.load(f)

            # Decompress elevation data
            with open(zst_file, "rb") as f:
                compressed_data = f.read()

            decompressor = zstd.ZstdDecompressor()
            raw_bytes = decompressor.decompress(compressed_data)

            # Reconstruct elevation array
            elevation_data = np.frombuffer(raw_bytes, dtype=metadata["dtype"])
            elevation_data = elevation_data.reshape(metadata["shape"])

            # Write to temporary TIF
            tif_file = self.temp_dir / f"{region_id}.tif"
            transform = rasterio.transform.from_bounds(
                metadata["bounds"]["left"],
                metadata["bounds"]["bottom"],
                metadata["bounds"]["right"],
                metadata["bounds"]["top"],
                metadata["shape"][1],
                metadata["shape"][0],
            )

            with rasterio.open(
                tif_file,
                "w",
                driver="GTiff",
                height=metadata["shape"][0],
                width=metadata["shape"][1],
                count=1,
                dtype=metadata["dtype"],
                crs=metadata["crs"],
                transform=transform,
                nodata=metadata["nodata_value"],
            ) as dst:
                dst.write(elevation_data, 1)

            # Only log errors, not every successful ingestion
            return tif_file

        except Exception as e:
            logger.error(f"Failed to ingest {region_id}: {e}")
            return None

    def deg2num(self, lat_deg, lon_deg, zoom):
        """Convert lat/lon to tile numbers."""
        lat_rad = math.radians(lat_deg)
        n = 2.0**zoom
        xtile = int((lon_deg + 180.0) / 360.0 * n)
        ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        return (xtile, ytile)

    def num2deg(self, xtile, ytile, zoom):
        """Convert tile numbers to lat/lon."""
        n = 2.0**zoom
        lon_deg = xtile / n * 360.0 - 180.0
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
        lat_deg = math.degrees(lat_rad)
        return (lat_deg, lon_deg)

    def create_elevation_tile(self, src, xtile, ytile, zoom, tile_size=256):
        """Create a single elevation tile as PNG."""
        # Get tile bounds in lat/lon
        lat_north, lon_west = self.num2deg(xtile, ytile, zoom)
        lat_south, lon_east = self.num2deg(xtile + 1, ytile + 1, zoom)

        # Convert to source CRS bounds
        try:
            from rasterio.warp import transform_bounds

            bounds = transform_bounds(
                "EPSG:4326", src.crs, lon_west, lat_south, lon_east, lat_north
            )
        except:
            # Fallback if transform fails
            bounds = (lon_west, lat_south, lon_east, lat_north)

        # Check if bounds intersect with raster
        src_bounds = src.bounds
        if (
            bounds[2] <= src_bounds.left
            or bounds[0] >= src_bounds.right
            or bounds[3] <= src_bounds.bottom
            or bounds[1] >= src_bounds.top
        ):
            return None  # No intersection

        # Read data for this tile
        try:
            from rasterio.enums import Resampling
            from rasterio.windows import from_bounds

            window = from_bounds(*bounds, src.transform)
            data = src.read(
                1,
                window=window,
                out_shape=(tile_size, tile_size),
                resampling=Resampling.cubic,
            )

            # Handle nodata values
            if src.nodata is not None:
                data = np.ma.masked_equal(data, src.nodata)

            # Normalize elevation data to 0-255 for PNG
            if data.size > 0 and not np.ma.is_masked(data):
                data_min, data_max = data.min(), data.max()
                if data_max > data_min:
                    normalized = (
                        (data - data_min) / (data_max - data_min) * 255
                    ).astype(np.uint8)
                else:
                    normalized = np.zeros_like(data, dtype=np.uint8)
            else:
                normalized = np.zeros((tile_size, tile_size), dtype=np.uint8)

            # Create PIL Image and save as PNG
            img = Image.fromarray(normalized, "L")  # Grayscale
            return img

        except Exception as e:
            logger.warning(f"Failed to create tile {xtile}/{ytile} at zoom {zoom}: {e}")
            return None

    def process_tiles(self, tif_files: list[Path]) -> bool:
        """Process TIF files into PNG tiles using rasterio and PIL."""
        try:
            # Silent processing - no logs except errors

            # Create tiles output directory
            tiles_dir = self.output_dir / "tiles"
            tiles_dir.mkdir(parents=True, exist_ok=True)

            # Process each TIF file individually first, then combine
            processed_files = []
            for tif_file in tif_files:
                try:
                    # Validate file first
                    with rasterio.open(tif_file) as src:
                        if src.count == 0 or src.width == 0 or src.height == 0:
                            continue

                    processed_files.append(tif_file)

                except Exception as e:
                    continue

            if not processed_files:
                logger.error("No valid TIF files to process")
                return False

            total_tiles_created = 0

            # Process each file to create tiles
            for tif_file in tqdm(processed_files, desc="Creating tiles from TIF files"):
                try:
                    with rasterio.open(tif_file) as src:
                        # Get bounds in lat/lon
                        bounds = src.bounds

                        if src.crs != "EPSG:4326":
                            try:
                                from rasterio.warp import transform_bounds

                                bounds = transform_bounds(src.crs, "EPSG:4326", *bounds)
                            except:
                                continue

                        # Generate tiles for zoom levels 8-12
                        for zoom in range(8, 13):
                            # Calculate tile range for this zoom level
                            # bounds = (left, bottom, right, top)
                            min_x, max_y = self.deg2num(
                                bounds[1], bounds[0], zoom
                            )  # bottom-left -> top-left
                            max_x, min_y = self.deg2num(
                                bounds[3], bounds[2], zoom
                            )  # top-right -> bottom-right

                            # Ensure proper ordering
                            if min_x > max_x:
                                min_x, max_x = max_x, min_x
                            if min_y > max_y:
                                min_y, max_y = max_y, min_y

                            # Calculate total tiles for this zoom level for progress bar
                            total_tiles_for_zoom = (max_x - min_x + 1) * (
                                max_y - min_y + 1
                            )

                            with tqdm(
                                total=total_tiles_for_zoom,
                                desc=f"Zoom {zoom}",
                                leave=False,
                            ) as pbar:
                                for x in range(min_x, max_x + 1):
                                    for y in range(min_y, max_y + 1):
                                        # Create tile
                                        tile_img = self.create_elevation_tile(
                                            src, x, y, zoom
                                        )
                                        if tile_img:
                                            # Save tile
                                            tile_dir = tiles_dir / str(zoom) / str(x)
                                            tile_dir.mkdir(parents=True, exist_ok=True)
                                            tile_path = tile_dir / f"{y}.png"
                                            tile_img.save(tile_path)
                                            total_tiles_created += 1
                                        pbar.update(1)

                except Exception as e:
                    continue

            if total_tiles_created == 0:
                logger.error("No PNG tiles were generated")
                return False

            return True

        except Exception as e:
            logger.error(f"Tile processing failed: {e}")
            return False

    def deploy_region(
        self, regions: list[str], max_workers: int = 4
    ) -> dict[str, bool]:
        """Deploy elevation data for specified regions."""
        # Reduce logging verbosity during processing
        logging.getLogger().setLevel(logging.WARNING)

        results = {}
        tif_files = []
        total_size_mb = 0

        # Get initial disk space
        disk_usage = shutil.disk_usage(self.temp_dir)
        initial_free_gb = disk_usage.free / (1024**3)

        print(f"🗂️  Available disk space: {initial_free_gb:.1f}GB")
        print(f"📊 Processing {len(regions)} elevation tiles...")

        # Phase 1: Ingest data
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_region = {
                executor.submit(self.ingest_compressed, region): region
                for region in regions
            }

            completed = 0
            last_progress_time = time.time()
            start_time = time.time()

            for future in as_completed(future_to_region):
                region = future_to_region[future]
                try:
                    tif_file = future.result()
                    if tif_file:
                        tif_files.append(tif_file)
                        results[region] = True
                        # Calculate file size
                        file_size_mb = tif_file.stat().st_size / (1024 * 1024)
                        total_size_mb += file_size_mb
                    else:
                        results[region] = False
                except Exception as e:
                    logger.error(f"Failed {region}: {e}")
                    results[region] = False

                completed += 1
                success_count = sum(1 for r in results.values() if r)

                # Show progress every 10 files or every 5 seconds
                current_time = time.time()
                if completed % 10 == 0 or current_time - last_progress_time > 5:
                    # Calculate ETA
                    elapsed_time = current_time - start_time
                    if completed > 0:
                        avg_time_per_tile = elapsed_time / completed
                        remaining_tiles = len(regions) - completed
                        eta_seconds = remaining_tiles * avg_time_per_tile
                        eta_minutes = eta_seconds / 60
                        eta_str = (
                            f"{eta_minutes:.0f}m"
                            if eta_minutes > 1
                            else f"{eta_seconds:.0f}s"
                        )
                    else:
                        eta_str = "calculating..."

                    # Check current disk usage
                    current_disk = shutil.disk_usage(self.temp_dir)
                    current_free_gb = current_disk.free / (1024**3)
                    used_gb = initial_free_gb - current_free_gb

                    percent_complete = (completed / len(regions)) * 100
                    progress_line = (
                        f"✅ {completed:4d}/{len(regions)} ({percent_complete:5.1f}%) | "
                        f"{success_count} successful | "
                        f"{total_size_mb:.1f}MB processed | "
                        f"💾 {used_gb:.1f}GB used | "
                        f"⏱️  ETA: {eta_str}"
                    )

                    # Use \r to overwrite the same line
                    print(f"\r{progress_line}", end="", flush=True)
                    last_progress_time = current_time

        print(
            f"\n🔄 Phase 1 complete: {success_count}/{len(regions)} tiles ingested ({total_size_mb:.1f}MB)"
        )

        # Phase 2: Process tiles
        if tif_files:
            print("🎨 Phase 2: Converting to PNG tiles...")
            success = self.process_tiles(tif_files)
            if not success:
                logger.error("Tile processing failed")
                return results
            print("✅ Phase 2 complete: PNG tiles generated")

        # Phase 3: Cleanup
        print("🧹 Phase 3: Cleaning up temporary files...")
        for tif_file in tif_files:
            tif_file.unlink()

        # Final disk usage check
        final_disk = shutil.disk_usage(self.temp_dir)
        final_free_gb = final_disk.free / (1024**3)
        total_used_gb = initial_free_gb - final_free_gb

        successful = sum(1 for success in results.values() if success)

        # Check tile output
        tiles_dir = self.output_dir / "tiles"
        if tiles_dir.exists():
            tile_count = sum(1 for _ in tiles_dir.rglob("*.png"))
            tile_size_mb = sum(f.stat().st_size for f in tiles_dir.rglob("*.png")) / (
                1024 * 1024
            )
        else:
            tile_count = 0
            tile_size_mb = 0

        print("\n🎉 Processing complete!")
        print(f"   📊 {successful}/{len(regions)} regions successfully processed")
        print(f"   💾 {total_used_gb:.1f}GB net disk space used")
        print(f"   📁 {total_size_mb:.1f}MB of elevation data processed")
        if tile_count > 0:
            print(f"   🗺️  {tile_count} PNG tiles generated ({tile_size_mb:.1f}MB)")
            print(f"   📍 Tiles available at: {tiles_dir}")
        else:
            print("   ⚠️  No PNG tiles generated")

        # Restore normal logging level
        logging.getLogger().setLevel(logging.INFO)
        logger.info(f"Successfully deployed {successful}/{len(regions)} regions")
        return results


def get_regions_by_area() -> dict[str, list[str]]:
    """Predefined region sets for common deployment scenarios."""
    return {
        "miami": ["n25_w080_1arc_v3", "n25_w081_1arc_v3"],
        "new_orleans": ["n29_w090_1arc_v3", "n30_w090_1arc_v3"],
        "houston": ["n29_w095_1arc_v3", "n30_w095_1arc_v3"],
        "nyc": ["n40_w074_1arc_v3", "n41_w074_1arc_v3"],
        "gulf_coast": [
            f"n{lat}_w{lng:03d}_1arc_v3"
            for lat in range(25, 31)
            for lng in range(82, 99)
        ],
    }


def main():
    """Main processing pipeline."""
    parser = argparse.ArgumentParser(
        description="Process elevation data for flood mapping"
    )
    parser.add_argument("--test", action="store_true", help="Test with one tile")
    parser.add_argument("--all", action="store_true", help="Process all USA tiles")
    parser.add_argument(
        "--tiles-only",
        action="store_true",
        help="Skip ingestion, just generate tiles from existing TIFs",
    )
    parser.add_argument("--workers", type=int, default=4, help="Processing workers")

    args = parser.parse_args()

    processor = ElevationProcessor(
        data_dir=Path.cwd(), output_dir=Path("processed_data/tiles")
    )

    compressed_dir = Path("compressed_data/usa")
    if not compressed_dir.exists():
        logger.error(f"Compressed data directory not found: {compressed_dir}")
        return

    all_tiles = sorted([f.stem for f in compressed_dir.glob("*.zst")])

    if args.tiles_only:
        # Skip decompression, just process existing TIF files
        logger.info("Tiles-only mode: processing existing TIF files")
        temp_tifs = list(processor.temp_dir.glob("*.tif"))
        if not temp_tifs:
            logger.error("No TIF files found in temp/processing directory")
            return

        logger.info(f"Found {len(temp_tifs)} existing TIF files")
        start_time = time.time()

        if processor.process_tiles(temp_tifs):
            logger.info("Tile generation completed successfully")
        else:
            logger.error("Tile generation failed")

        elapsed = time.time() - start_time
        logger.info(f"Processing completed in {elapsed / 60:.1f} minutes")
        return

    if args.test:
        # Test with first available tile
        tiles = [all_tiles[0]] if all_tiles else []
        logger.info(f"Testing pipeline with: {tiles[0] if tiles else 'no tiles found'}")
    elif args.all:
        tiles = all_tiles
        logger.info(f"Processing all {len(tiles)} USA tiles")
    else:
        # Default test
        tiles = [all_tiles[0]] if all_tiles else []
        logger.info(
            f"No option specified, testing with: {tiles[0] if tiles else 'no tiles found'}"
        )

    if not tiles:
        logger.error("No tiles to process")
        return

    # Execute processing
    start_time = time.time()
    results = processor.deploy_region(tiles, args.workers)

    elapsed = time.time() - start_time
    successful = sum(1 for success in results.values() if success)

    logger.info(f"Processing completed in {elapsed / 60:.1f} minutes")
    logger.info(f"Success rate: {successful}/{len(tiles)} tiles")

    if successful > 0:
        logger.info("New elevation data ready for serving")


if __name__ == "__main__":
    main()
