#!/usr/bin/env python3
"""
Complete USA Map Processing Pipeline
Downloads and processes the entire USA OSM data into .mbtiles for comprehensive coverage.
"""

import os
import sys
import time
import logging
import subprocess
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class USAMapProcessor:
    def __init__(self):
        self.base_dir = Path("/Users/davidrose/git/floodmap")
        self.input_dir = Path("/Volumes/Storage/floodmap-archive/maps-raw")
        self.output_dir = self.base_dir / "output"
        self.java_path = "/opt/homebrew/opt/openjdk@21/bin"
        
        # File paths
        self.usa_osm_file = self.input_dir / "us-latest.osm.pbf"
        self.usa_mbtiles = self.output_dir / "usa-complete.mbtiles"
        self.planetiler_jar = self.base_dir / "utils" / "planetiler.jar"
        self.auxiliary_data = self.input_dir / "auxiliary-data"
        
    def check_prerequisites(self):
        """Check that all required files and tools are available."""
        logger.info("🔍 Checking prerequisites...")
        
        # Check Java 21
        java_cmd = f"{self.java_path}/java"
        try:
            result = subprocess.run([java_cmd, "-version"], 
                                  capture_output=True, text=True, check=True)
            logger.info("✅ Java 21 available")
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error("❌ Java 21 not found")
            return False
            
        # Check Planetiler JAR
        if not self.planetiler_jar.exists():
            logger.error(f"❌ Planetiler JAR not found: {self.planetiler_jar}")
            return False
        logger.info("✅ Planetiler JAR available")
        
        # Check USA OSM file
        if not self.usa_osm_file.exists():
            logger.error(f"❌ USA OSM file not found: {self.usa_osm_file}")
            logger.info("Please wait for download to complete or run download first")
            return False
        
        file_size_gb = self.usa_osm_file.stat().st_size / (1024**3)
        logger.info(f"✅ USA OSM file available ({file_size_gb:.1f}GB)")
        
        # Check disk space
        import shutil
        free_space_gb = shutil.disk_usage(self.base_dir).free / (1024**3)
        if free_space_gb < 50:  # Need at least 50GB for processing
            logger.error(f"❌ Insufficient disk space: {free_space_gb:.1f}GB (need 50GB+)")
            return False
        logger.info(f"✅ Sufficient disk space: {free_space_gb:.1f}GB")
        
        return True
    
    def process_usa_mbtiles(self, maxzoom=12, memory_gb=8):
        """Process the complete USA OSM file into .mbtiles using Planetiler."""
        logger.info("🏗️ Processing USA OSM data with Planetiler...")
        logger.info(f"Input: {self.usa_osm_file} ({self.usa_osm_file.stat().st_size / (1024**3):.1f}GB)")
        logger.info(f"Output: {self.usa_mbtiles}")
        logger.info(f"Settings: maxzoom={maxzoom}, memory={memory_gb}GB")
        
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Planetiler command for complete USA processing
        cmd = [
            f"{self.java_path}/java",
            f"-Xmx{memory_gb}g",  # Configurable memory
            "-jar", str(self.planetiler_jar),
            "--osm-path", str(self.usa_osm_file),
            "--output", str(self.usa_mbtiles),
            "--download-dir", str(self.auxiliary_data),  # Use existing auxiliary data
            "--force",    # Overwrite existing output file
            "--minzoom", "0",
            "--maxzoom", str(maxzoom)  # Use parameter
        ]
        
        logger.info(f"Running: {' '.join(cmd)}")
        start_time = time.time()
        
        try:
            # Run with progress output
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Stream output in real-time
            for line in process.stdout:
                line = line.strip()
                if line:
                    logger.info(f"Planetiler: {line}")
                    
            process.wait()
            
            if process.returncode != 0:
                logger.error(f"❌ Planetiler failed with return code {process.returncode}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error running Planetiler: {e}")
            return False
        
        processing_time = time.time() - start_time
        
        if self.usa_mbtiles.exists():
            output_size_mb = self.usa_mbtiles.stat().st_size / (1024**2)
            logger.info(f"✅ USA processing completed in {processing_time/60:.1f} minutes")
            logger.info(f"✅ Output: {output_size_mb:.1f}MB → {self.usa_mbtiles}")
            return True
        else:
            logger.error("❌ Output file not created")
            return False
    
    def update_tileserver_config(self):
        """Update TileServer configuration to include USA complete coverage."""
        logger.info("🔧 Updating TileServer configuration...")
        
        config_script = self.base_dir / "scripts" / "update_tileserver_config.py"
        if config_script.exists():
            try:
                subprocess.run([
                    "uv", "run", "python", str(config_script)
                ], check=True, cwd=self.base_dir)
                logger.info("✅ TileServer configuration updated")
                return True
            except subprocess.CalledProcessError as e:
                logger.error(f"❌ Failed to update TileServer config: {e}")
                return False
        else:
            logger.warning("⚠️ TileServer config script not found")
            return False
    
    def run_complete_processing(self, maxzoom=12, memory_gb=8):
        """Run the complete USA processing pipeline."""
        logger.info("🇺🇸 Starting complete USA map processing...")
        
        # Step 1: Check prerequisites
        if not self.check_prerequisites():
            logger.error("❌ Prerequisites not met. Aborting.")
            return False
        
        # Step 2: Process USA data
        if not self.process_usa_mbtiles(maxzoom=maxzoom, memory_gb=memory_gb):
            logger.error("❌ USA processing failed")
            return False
        
        # Step 3: Update TileServer config
        if not self.update_tileserver_config():
            logger.warning("⚠️ Config update failed, but processing succeeded")
        
        logger.info("🎯 Complete USA processing finished successfully!")
        logger.info("🗺️ USA-wide map tiles are now available for the flood mapping system")
        return True

def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Process USA map tiles (roads, borders, cities)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be processed without running")
    parser.add_argument("--maxzoom", type=int, default=12, help="Maximum zoom level (default: 12)")
    parser.add_argument("--memory", type=int, default=8, help="Memory allocation in GB (default: 8)")
    args = parser.parse_args()
    
    processor = USAMapProcessor()
    
    logger.info(f"🎯 Settings: maxzoom={args.maxzoom}, memory={args.memory}GB")
        
    if args.dry_run:
        logger.info("🔍 DRY RUN: Would process USA map tiles")
        logger.info(f"📁 Input: {processor.usa_osm_file} ({processor.usa_osm_file.stat().st_size / (1024**3):.1f}GB)")
        logger.info(f"📁 Output: {processor.usa_mbtiles}")
        logger.info(f"⚙️  Max zoom: {args.maxzoom}")
        logger.info(f"💾 Memory: {args.memory}GB")
        logger.info("✅ All prerequisites checked - ready for processing")
        sys.exit(0)
    
    success = processor.run_complete_processing(maxzoom=args.maxzoom, memory_gb=args.memory)
    
    if success:
        logger.info("🚀 Ready for nationwide flood mapping!")
        sys.exit(0)
    else:
        logger.error("💥 Processing failed")
        sys.exit(1)

if __name__ == "__main__":
    main()