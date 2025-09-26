#!/usr/bin/env python3
"""
Production script to expand geographic coverage for elevation data.
Handles decompression of nationwide .zst files and processing to PNG tiles.
"""

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import rasterio
import zstandard as zstd
from tqdm import tqdm

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/coverage_expansion.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


class CoverageExpander:
    """Handles expansion of elevation coverage to new regions."""

    def __init__(self, compressed_dir: Path, output_dir: Path, temp_dir: Path):
        self.compressed_dir = Path(compressed_dir)
        self.output_dir = Path(output_dir)
        self.temp_dir = Path(temp_dir)

        # Ensure directories exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        Path("logs").mkdir(exist_ok=True)

    def get_available_regions(self) -> list[dict]:
        """Get list of available compressed regions."""
        regions = []
        for zst_file in self.compressed_dir.glob("*.zst"):
            json_file = zst_file.with_suffix(".json")
            if json_file.exists():
                with open(json_file) as f:
                    metadata = json.load(f)
                regions.append(
                    {
                        "tile_id": metadata["tile_id"],
                        "zst_file": zst_file,
                        "json_file": json_file,
                        "bounds": metadata["bounds"],
                        "size_mb": zst_file.stat().st_size / 1024 / 1024,
                    }
                )
        return sorted(regions, key=lambda x: x["tile_id"])

    def decompress_tile(self, region: dict) -> Path:
        """Decompress a single .zst tile to TIF format."""
        try:
            # Read metadata
            with open(region["json_file"]) as f:
                metadata = json.load(f)

            # Read and decompress data
            with open(region["zst_file"], "rb") as f:
                compressed_data = f.read()

            decompressor = zstd.ZstdDecompressor()
            raw_bytes = decompressor.decompress(compressed_data)

            # Reconstruct elevation array
            elevation_data = np.frombuffer(raw_bytes, dtype=metadata["dtype"])
            elevation_data = elevation_data.reshape(metadata["shape"])

            # Create TIF file
            tif_file = self.temp_dir / f"{metadata['tile_id']}.tif"

            transform = rasterio.transform.from_bounds(
                metadata["bounds"]["left"],
                metadata["bounds"]["bottom"],
                metadata["bounds"]["right"],
                metadata["bounds"]["top"],
                metadata["shape"][1],  # width
                metadata["shape"][0],  # height
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

            logger.info(f"Decompressed {region['tile_id']} -> {tif_file}")
            return tif_file

        except Exception as e:
            logger.error(f"Failed to decompress {region['tile_id']}: {e}")
            raise

    def process_regions(
        self, region_names: list[str], max_workers: int = 4
    ) -> dict[str, str]:
        """Process multiple regions with progress tracking."""

        available_regions = self.get_available_regions()
        region_map = {r["tile_id"]: r for r in available_regions}

        # Filter to requested regions
        regions_to_process = []
        for name in region_names:
            if name in region_map:
                regions_to_process.append(region_map[name])
            else:
                logger.warning(f"Region {name} not found in compressed data")

        if not regions_to_process:
            logger.error("No valid regions to process")
            return {}

        logger.info(
            f"Processing {len(regions_to_process)} regions with {max_workers} workers"
        )

        results = {}
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Submit decompression tasks
            future_to_region = {
                executor.submit(self.decompress_tile, region): region["tile_id"]
                for region in regions_to_process
            }

            # Track progress
            with tqdm(
                total=len(regions_to_process), desc="Decompressing tiles"
            ) as pbar:
                for future in as_completed(future_to_region):
                    region_id = future_to_region[future]
                    try:
                        tif_file = future.result()
                        results[region_id] = str(tif_file)
                        pbar.set_postfix(current=region_id)
                    except Exception as e:
                        logger.error(f"Failed processing {region_id}: {e}")
                        results[region_id] = f"ERROR: {e}"
                    pbar.update(1)

        return results

    def run_tile_processing(self, tif_files: list[Path]) -> bool:
        """Run the existing tile processing pipeline on decompressed TIFs."""
        try:
            # Import and run the existing processing pipeline
            sys.path.append("scripts")
            from process_tif import main as process_tif_main

            logger.info(f"Processing {len(tif_files)} TIF files to PNG tiles")

            # Set environment variables for the processing script
            original_input_dir = os.environ.get("INPUT_DIR")
            os.environ["INPUT_DIR"] = str(self.temp_dir)

            try:
                # Run tile processing
                process_tif_main()
                logger.info("✅ Tile processing completed successfully")
                return True
            finally:
                # Restore original environment
                if original_input_dir:
                    os.environ["INPUT_DIR"] = original_input_dir
                else:
                    os.environ.pop("INPUT_DIR", None)

        except Exception as e:
            logger.error(f"Tile processing failed: {e}")
            return False

    def cleanup_temp_files(self):
        """Clean up temporary TIF files."""
        for tif_file in self.temp_dir.glob("*.tif"):
            tif_file.unlink()
            logger.debug(f"Cleaned up {tif_file}")


def get_city_regions() -> dict[str, list[str]]:
    """Predefined city regions for easy expansion."""
    return {
        "miami": ["n25_w080_1arc_v3", "n25_w081_1arc_v3"],
        "new_orleans": ["n29_w090_1arc_v3", "n30_w090_1arc_v3"],
        "houston": ["n29_w095_1arc_v3", "n30_w095_1arc_v3"],
        "tampa": ["n27_w082_1arc_v3", "n28_w082_1arc_v3"],  # Already processed
    }


def main():
    """Main expansion pipeline."""
    parser = argparse.ArgumentParser(
        description="Expand elevation coverage to new regions"
    )
    parser.add_argument("--regions", nargs="+", help="Specific region tiles to process")
    parser.add_argument(
        "--city", choices=get_city_regions().keys(), help="Process predefined city"
    )
    parser.add_argument(
        "--list-available", action="store_true", help="List available regions"
    )
    parser.add_argument(
        "--test", action="store_true", help="Test mode: process Miami only"
    )
    parser.add_argument(
        "--workers", type=int, default=4, help="Number of parallel workers"
    )

    args = parser.parse_args()

    # Initialize expander
    expander = CoverageExpander(
        compressed_dir="compressed_data/usa",
        output_dir="processed_data/tiles",
        temp_dir="temp/elevation_processing",
    )

    if args.list_available:
        regions = expander.get_available_regions()
        print(f"\n📊 Available regions ({len(regions)} total):")
        for region in regions[:20]:  # Show first 20
            bounds = region["bounds"]
            print(
                f"  {region['tile_id']}: {bounds['bottom']:.1f}°N, {bounds['left']:.1f}°W ({region['size_mb']:.1f}MB)"
            )
        if len(regions) > 20:
            print(f"  ... and {len(regions) - 20} more")
        return

    # Determine regions to process
    regions_to_process = []
    if args.test:
        regions_to_process = ["n25_w080_1arc_v3"]  # Miami test
        logger.info("🧪 TEST MODE: Processing Miami only")
    elif args.city:
        regions_to_process = get_city_regions()[args.city]
        logger.info(f"🏙️ Processing city: {args.city}")
    elif args.regions:
        regions_to_process = args.regions
        logger.info(f"📍 Processing specific regions: {regions_to_process}")
    else:
        logger.error("Must specify --regions, --city, --test, or --list-available")
        return

    # Process regions
    start_time = time.time()
    logger.info(f"🚀 Starting coverage expansion: {regions_to_process}")

    try:
        # Step 1: Decompress tiles
        results = expander.process_regions(regions_to_process, args.workers)

        successful_tifs = [
            Path(path) for path in results.values() if not path.startswith("ERROR")
        ]
        failed_regions = [
            region for region, path in results.items() if path.startswith("ERROR")
        ]

        if failed_regions:
            logger.warning(f"❌ Failed regions: {failed_regions}")

        if not successful_tifs:
            logger.error("❌ No tiles successfully decompressed")
            return

        logger.info(f"✅ Decompressed {len(successful_tifs)} tiles successfully")

        # Step 2: Process to PNG tiles
        if expander.run_tile_processing(successful_tifs):
            logger.info("✅ PNG tile generation completed")
        else:
            logger.error("❌ PNG tile generation failed")
            return

        # Step 3: Cleanup
        expander.cleanup_temp_files()

        elapsed = time.time() - start_time
        logger.info(f"🎉 Coverage expansion completed in {elapsed / 60:.1f} minutes")
        logger.info("🗺️ New regions should now be available for elevation overlays")

    except Exception as e:
        logger.error(f"❌ Pipeline failed: {e}")
        raise


if __name__ == "__main__":
    main()
