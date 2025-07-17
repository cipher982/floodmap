#!/usr/bin/env python3
"""
Auto-update TileServer-GL configuration when new .mbtiles are available.
Scans for .mbtiles files and updates the config.json accordingly.
"""

import json
import os
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def update_tileserver_config():
    """Update TileServer-GL configuration with available .mbtiles files."""
    base_dir = Path("/Users/davidrose/git/floodmap")
    config_path = base_dir / "map_data" / "config.json"
    
    # Find all .mbtiles files
    sources = {}
    
    # Main map data directory
    map_data_dir = base_dir / "map_data"
    if map_data_dir.exists():
        for mbtiles_file in map_data_dir.glob("*.mbtiles"):
            source_name = mbtiles_file.stem
            sources[source_name] = {
                "type": "mbtiles",
                "path": mbtiles_file.name
            }
            logger.info(f"Found main tile source: {source_name}")
    
    # Regional map data directory
    regions_dir = map_data_dir / "regions"
    if regions_dir.exists():
        for mbtiles_file in regions_dir.glob("*.mbtiles"):
            source_name = mbtiles_file.stem
            sources[source_name] = {
                "type": "mbtiles",
                "path": f"regions/{mbtiles_file.name}"
            }
            logger.info(f"Found regional tile source: {source_name}")
    
    if not sources:
        logger.warning("No .mbtiles files found!")
        return False
    
    # Read existing config or create new one
    config = {
        "options": {
            "paths": {
                "root": "/data",
                "fonts": "fonts",
                "sprites": "sprites",
                "styles": "styles",
                "mbtiles": "/data"
            },
            "serveAllFonts": True,
            "domains": ["*"]
        },
        "sources": sources,
        "styles": {
            "basic": {
                "style": "basic",
                "tilejson": {
                    "format": "pbf",
                    "bounds": [-180, -85, 180, 85]
                }
            }
        }
    }
    
    # Write updated config
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    logger.info(f"✅ Updated TileServer config with {len(sources)} sources")
    logger.info(f"Sources: {', '.join(sources.keys())}")
    return True

def main():
    """Main function."""
    logger.info("🔄 Updating TileServer configuration...")
    success = update_tileserver_config()
    if success:
        logger.info("🎯 Configuration update completed successfully")
    else:
        logger.error("❌ Configuration update failed")

if __name__ == "__main__":
    main()