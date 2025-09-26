#!/usr/bin/env python3
"""
Smart NASA SRTM download - only downloads tiles that actually exist
Uses your existing tile list as a reference for what's needed
"""

import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import rasterio
from tqdm import tqdm

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration
OUTPUT_DIR = Path("/Volumes/Storage/floodmap-nasa-elevation-raw")
TEMP_DIR = OUTPUT_DIR / "temp"
EXISTING_DIR = Path("/Volumes/Storage/floodmap-archive/elevation-raw")
MAX_WORKERS = 6
RETRY_COUNT = 2  # Reduce retries for 404s


def setup_directories():
    """Create necessary directories."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)
    logger.info(f"Setup directories: {OUTPUT_DIR}")


def get_existing_tile_list():
    """Get list of tiles from existing collection to know what's actually needed."""
    if not EXISTING_DIR.exists():
        logger.error(f"Existing data directory not found: {EXISTING_DIR}")
        return []

    tiles = []
    for tif_file in EXISTING_DIR.glob("n*_w*_1arc_v3.tif"):
        # Parse filename: n27_w081_1arc_v3.tif -> N27W081
        parts = tif_file.stem.split("_")
        if len(parts) >= 3:
            lat_part = parts[0]  # n27
            lon_part = parts[1]  # w081

            try:
                lat = int(lat_part[1:])  # 27
                lon = int(lon_part[1:])  # 81

                lat_str = f"N{lat:02d}"
                lon_str = f"W{lon:03d}"
                tile_name = f"{lat_str}{lon_str}"

                tiles.append(
                    {
                        "name": tile_name,
                        "lat": lat,
                        "lon": -lon,  # Convert to negative
                        "url": f"https://e4ftl01.cr.usgs.gov/MEASURES/SRTMGL1.003/2000.02.11/{tile_name}.SRTMGL1.hgt.zip",
                        "output_name": tif_file.name,
                    }
                )
            except ValueError:
                logger.warning(f"Could not parse filename: {tif_file.name}")

    logger.info(f"Found {len(tiles)} existing tiles to replace with NASA data")
    return tiles


def download_and_convert_tile(tile):
    """Download and convert a single SRTM tile."""
    zip_path = TEMP_DIR / f"{tile['name']}.SRTMGL1.hgt.zip"
    hgt_path = TEMP_DIR / f"{tile['name']}.hgt"
    output_path = OUTPUT_DIR / tile["output_name"]

    # Skip if already exists
    if output_path.exists():
        return {"success": True, "tile": tile["name"], "status": "exists"}

    try:
        # Download with reduced retry for 404s
        for attempt in range(RETRY_COUNT):
            try:
                cmd = [
                    "curl",
                    "-f",
                    "-L",
                    "-n",
                    "--connect-timeout",
                    "30",
                    "-b",
                    os.path.expanduser("~/.urs_cookies"),
                    "-c",
                    os.path.expanduser("~/.urs_cookies"),
                    "-o",
                    str(zip_path),
                    tile["url"],
                ]

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    break
                elif result.returncode == 22:  # HTTP 404
                    return {
                        "success": False,
                        "tile": tile["name"],
                        "error": "404 - Tile not available on NASA server",
                    }
                else:
                    if attempt == RETRY_COUNT - 1:
                        return {
                            "success": False,
                            "tile": tile["name"],
                            "error": f"Download failed: HTTP {result.returncode}",
                        }
                    time.sleep(1)  # Shorter wait for retries
            except subprocess.TimeoutExpired:
                if attempt == RETRY_COUNT - 1:
                    return {
                        "success": False,
                        "tile": tile["name"],
                        "error": "Download timeout",
                    }

        # Extract
        extract_cmd = ["unzip", "-o", "-j", str(zip_path), "-d", str(TEMP_DIR)]
        result = subprocess.run(extract_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return {
                "success": False,
                "tile": tile["name"],
                "error": f"Extract failed: {result.stderr}",
            }

        # Convert HGT to GeoTIFF
        convert_hgt_to_geotiff(hgt_path, output_path, tile["lat"], tile["lon"])

        # Cleanup temp files
        zip_path.unlink(missing_ok=True)
        hgt_path.unlink(missing_ok=True)

        return {"success": True, "tile": tile["name"], "status": "downloaded"}

    except Exception as e:
        logger.error(f"Error processing {tile['name']}: {e}")
        return {"success": False, "tile": tile["name"], "error": str(e)}


def convert_hgt_to_geotiff(hgt_path, output_path, lat, lon):
    """Convert SRTM .hgt file to GeoTIFF format using rasterio."""
    import numpy as np
    from rasterio.transform import from_bounds

    # SRTM 1 arc-second files are 3601x3601 pixels covering exactly 1 degree
    width = height = 3601

    # Read the raw elevation data (16-bit big-endian signed integers)
    with open(hgt_path, "rb") as f:
        data = np.frombuffer(f.read(), dtype=">i2")

    # Reshape to 2D array and convert to native endianness
    elevation = data.reshape(height, width).astype(np.int16)

    # Define the geospatial transform (SRTM data goes from NW to SE)
    transform = from_bounds(lon, lat, lon + 1, lat + 1, width, height)

    # Write as GeoTIFF with LZW compression
    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="int16",
        crs="EPSG:4326",
        transform=transform,
        compress="lzw",
    ) as dst:
        dst.write(elevation, 1)


def main():
    """Main download orchestration."""
    print("🌍 Smart NASA SRTM Download (Existing Tiles Only)")
    print(f"📁 Output directory: {OUTPUT_DIR}")
    print(f"📂 Reference directory: {EXISTING_DIR}")
    print(f"🔧 Workers: {MAX_WORKERS}")
    print()

    setup_directories()
    tiles = get_existing_tile_list()

    if not tiles:
        print("❌ No existing tiles found to replace!")
        sys.exit(1)

    print(f"📦 Tiles to download: {len(tiles)}")
    print("🚀 Starting smart download...")
    print()

    # Process tiles with progress bar
    success_count = 0
    error_count = 0
    exists_count = 0
    not_available_count = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all download tasks
        future_to_tile = {
            executor.submit(download_and_convert_tile, tile): tile for tile in tiles
        }

        # Process results with progress bar
        with tqdm(total=len(tiles), desc="Processing tiles") as pbar:
            for future in as_completed(future_to_tile):
                result = future.result()

                if result["success"]:
                    if result.get("status") == "exists":
                        exists_count += 1
                    else:
                        success_count += 1
                else:
                    if "404" in result.get("error", ""):
                        not_available_count += 1
                    else:
                        error_count += 1
                        logger.error(
                            f"Failed: {result['tile']} - {result.get('error', 'Unknown error')}"
                        )

                pbar.update(1)
                pbar.set_postfix(
                    {
                        "Success": success_count,
                        "Exists": exists_count,
                        "N/A": not_available_count,
                        "Errors": error_count,
                    }
                )

    print()
    print("✅ Download Complete!")
    print("📊 Results:")
    print(f"   ✅ Downloaded: {success_count}")
    print(f"   📁 Already existed: {exists_count}")
    print(f"   🌊 Not available (likely ocean): {not_available_count}")
    print(f"   ❌ Errors: {error_count}")
    print(f"📁 Files saved to: {OUTPUT_DIR}")

    # Cleanup temp directory
    if TEMP_DIR.exists() and not any(TEMP_DIR.iterdir()):
        TEMP_DIR.rmdir()

    total_good = success_count + exists_count
    print(f"🎉 {total_good}/{len(tiles)} tiles successfully processed!")

    if not_available_count > 0:
        print(
            f"ℹ️  {not_available_count} tiles not available on NASA (likely pure ocean areas)"
        )


if __name__ == "__main__":
    main()
