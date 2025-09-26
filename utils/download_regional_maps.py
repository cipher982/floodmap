#!/usr/bin/env python3
"""
Download and process regional map data for comprehensive USA coverage.
Uses Planetiler to generate .mbtiles from OpenStreetMap data.
"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlretrieve

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Regional map data sources (Geofabrik OSM extracts)
REGIONS = {
    "california": {
        "name": "California",
        "url": "https://download.geofabrik.de/north-america/us/california-latest.osm.pbf",
        "expected_size_mb": 1200,
        "priority": 1,
    },
    "texas": {
        "name": "Texas",
        "url": "https://download.geofabrik.de/north-america/us/texas-latest.osm.pbf",
        "expected_size_mb": 800,
        "priority": 2,
    },
    "new-york": {
        "name": "New York",
        "url": "https://download.geofabrik.de/north-america/us/new-york-latest.osm.pbf",
        "expected_size_mb": 400,
        "priority": 3,
    },
    "florida": {
        "name": "Florida",
        "url": "https://download.geofabrik.de/north-america/us/florida-latest.osm.pbf",
        "expected_size_mb": 300,
        "priority": 4,
    },
    "illinois": {
        "name": "Illinois",
        "url": "https://download.geofabrik.de/north-america/us/illinois-latest.osm.pbf",
        "expected_size_mb": 250,
        "priority": 5,
    },
}


class RegionalMapProcessor:
    """Download and process regional map data."""

    def __init__(self, base_dir: str = "/Users/davidrose/git/floodmap"):
        self.base_dir = Path(base_dir)
        self.map_data_dir = self.base_dir / "map_data" / "regions"
        self.map_data_dir.mkdir(parents=True, exist_ok=True)

        # Check for Planetiler
        self.planetiler_jar = self.find_planetiler()
        if not self.planetiler_jar:
            logger.error("Planetiler not found. Please install it first.")
            sys.exit(1)

    def find_planetiler(self) -> str:
        """Find Planetiler JAR file."""
        possible_paths = [
            "/opt/homebrew/bin/planetiler",
            "/usr/local/bin/planetiler",
            str(self.base_dir / "planetiler.jar"),
            str(self.base_dir / "tools" / "planetiler.jar"),
        ]

        for path in possible_paths:
            if os.path.exists(path):
                return path

        # Try to download if not found
        logger.info("Downloading Planetiler...")
        planetiler_url = "https://github.com/onthegomap/planetiler/releases/latest/download/planetiler.jar"
        planetiler_path = str(self.base_dir / "planetiler.jar")

        try:
            urlretrieve(planetiler_url, planetiler_path)
            logger.info(f"Downloaded Planetiler to {planetiler_path}")
            return planetiler_path
        except Exception as e:
            logger.error(f"Failed to download Planetiler: {e}")
            return None

    def download_region(self, region_key: str) -> bool:
        """Download OSM data for a region."""
        region = REGIONS[region_key]
        pbf_path = self.map_data_dir / f"{region_key}.osm.pbf"

        if pbf_path.exists():
            size_mb = pbf_path.stat().st_size / (1024 * 1024)
            if size_mb > region["expected_size_mb"] * 0.8:  # 80% of expected size
                logger.info(f"✅ {region['name']} already downloaded ({size_mb:.1f}MB)")
                return True

        logger.info(
            f"🌍 Downloading {region['name']} ({region['expected_size_mb']}MB expected)..."
        )

        try:

            def progress_hook(block_num, block_size, total_size):
                if total_size > 0:
                    percent = min(100, (block_num * block_size / total_size) * 100)
                    mb_downloaded = (block_num * block_size) / (1024 * 1024)
                    total_mb = total_size / (1024 * 1024)
                    print(
                        f"\r📥 {region['name']}: {percent:.1f}% ({mb_downloaded:.1f}/{total_mb:.1f}MB)",
                        end="",
                        flush=True,
                    )

            urlretrieve(region["url"], str(pbf_path), reporthook=progress_hook)
            print()  # New line after progress

            # Verify download
            size_mb = pbf_path.stat().st_size / (1024 * 1024)
            logger.info(f"✅ Downloaded {region['name']}: {size_mb:.1f}MB")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to download {region['name']}: {e}")
            if pbf_path.exists():
                pbf_path.unlink()  # Remove partial download
            return False

    def process_region(self, region_key: str) -> bool:
        """Process OSM data into MBTiles."""
        region = REGIONS[region_key]
        pbf_path = self.map_data_dir / f"{region_key}.osm.pbf"
        mbtiles_path = self.map_data_dir / f"{region_key}.mbtiles"

        if not pbf_path.exists():
            logger.error(f"❌ PBF file not found: {pbf_path}")
            return False

        if mbtiles_path.exists():
            size_mb = mbtiles_path.stat().st_size / (1024 * 1024)
            logger.info(f"✅ {region['name']} already processed ({size_mb:.1f}MB)")
            return True

        logger.info(f"🏗️ Processing {region['name']} with Planetiler...")

        # Planetiler command - use OSM file directly instead of area name
        cmd = [
            "java",
            "-Xmx8g",  # 8GB heap size
            "-jar",
            self.planetiler_jar,
            "--download",  # Download required data sources
            "--osm-file",
            str(pbf_path),
            "--output",
            str(mbtiles_path),
            "--minzoom",
            "0",
            "--maxzoom",
            "14",
        ]

        try:
            start_time = time.time()
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)

            if result.returncode == 0:
                processing_time = time.time() - start_time
                size_mb = mbtiles_path.stat().st_size / (1024 * 1024)
                logger.info(
                    f"✅ Processed {region['name']} in {processing_time / 60:.1f}min → {size_mb:.1f}MB"
                )
                return True
            else:
                logger.error(f"❌ Planetiler failed for {region['name']}")
                logger.error(f"stdout: {result.stdout}")
                logger.error(f"stderr: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"❌ Processing timeout for {region['name']} after 1 hour")
            return False
        except Exception as e:
            logger.error(f"❌ Processing failed for {region['name']}: {e}")
            return False

    def update_tileserver_config(self):
        """Update TileServer-GL configuration for multi-region serving."""
        config_path = self.base_dir / "map_data" / "config.json"

        # Build sources for all processed regions
        sources = {}
        for region_key, region in REGIONS.items():
            mbtiles_path = self.map_data_dir / f"{region_key}.mbtiles"
            if mbtiles_path.exists():
                sources[region_key] = {
                    "type": "mbtiles",
                    "path": f"regions/{region_key}.mbtiles",
                }

        # Add Tampa (existing)
        tampa_path = self.base_dir / "map_data" / "tampa.mbtiles"
        if tampa_path.exists():
            sources["tampa"] = {"type": "mbtiles", "path": "tampa.mbtiles"}

        config = {
            "sources": sources,
            "styles": {
                "basic": {
                    "style": "basic",
                    "tilejson": {"format": "pbf", "bounds": [-180, -85, 180, 85]},
                }
            },
        }

        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

        logger.info(f"📝 Updated TileServer config with {len(sources)} regions")
        logger.info(f"Config: {config_path}")

    def process_priority_regions(self, max_regions: int = 3):
        """Process regions in priority order."""
        logger.info(f"🚀 Processing top {max_regions} priority regions...")

        # Sort regions by priority
        sorted_regions = sorted(REGIONS.items(), key=lambda x: x[1]["priority"])

        success_count = 0
        for region_key, region in sorted_regions[:max_regions]:
            logger.info(
                f"\n📍 Processing {region['name']} (Priority {region['priority']})"
            )

            # Download
            if self.download_region(region_key):
                # Process
                if self.process_region(region_key):
                    success_count += 1
                else:
                    logger.warning(
                        f"⚠️ Processing failed for {region['name']}, continuing..."
                    )
            else:
                logger.warning(f"⚠️ Download failed for {region['name']}, continuing...")

        logger.info(
            f"\n🎯 Completed {success_count}/{max_regions} regions successfully"
        )

        if success_count > 0:
            self.update_tileserver_config()
            return True
        return False


def main():
    """Main processing function."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Download and process regional map data"
    )
    parser.add_argument(
        "--region", help="Process specific region", choices=list(REGIONS.keys())
    )
    parser.add_argument(
        "--max-regions", type=int, default=3, help="Max regions to process"
    )
    parser.add_argument(
        "--download-only", action="store_true", help="Only download, don't process"
    )

    args = parser.parse_args()

    processor = RegionalMapProcessor()

    if args.region:
        # Process single region
        logger.info(f"Processing single region: {args.region}")
        success = processor.download_region(args.region)
        if success and not args.download_only:
            success = processor.process_region(args.region)
        if success:
            processor.update_tileserver_config()
    else:
        # Process priority regions
        processor.process_priority_regions(args.max_regions)


if __name__ == "__main__":
    main()
