#!/usr/bin/env python3
"""
Download complete USA SRTM coverage from NASA LP DAAC
Downloads and converts all SRTM tiles for USA coverage (24-50°N, 66-125°W)
"""
import os
import sys
import time
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess
import rasterio
from tqdm import tqdm

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
OUTPUT_DIR = Path("/Volumes/Storage/floodmap-nasa-elevation-raw")
TEMP_DIR = OUTPUT_DIR / "temp"
MAX_WORKERS = 4
RETRY_COUNT = 3

# USA bounding box
USA_BOUNDS = {
    'lat_min': 24,   # Southern Florida
    'lat_max': 50,   # Canadian border  
    'lon_min': -125, # West coast
    'lon_max': -66   # East coast
}

def setup_directories():
    """Create necessary directories."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)
    logger.info(f"Setup directories: {OUTPUT_DIR}")

def generate_tile_list():
    """Generate list of all SRTM tiles needed for USA coverage."""
    tiles = []
    
    for lat in range(USA_BOUNDS['lat_min'], USA_BOUNDS['lat_max'] + 1):
        for lon in range(USA_BOUNDS['lon_min'], USA_BOUNDS['lon_max'] + 1):
            # Convert to SRTM naming convention
            lat_str = f"N{lat:02d}" if lat >= 0 else f"S{abs(lat):02d}"
            lon_str = f"W{abs(lon):03d}" if lon < 0 else f"E{lon:03d}"
            
            tile_name = f"{lat_str}{lon_str}"
            tiles.append({
                'name': tile_name,
                'lat': lat,
                'lon': lon,
                'url': f"https://e4ftl01.cr.usgs.gov/MEASURES/SRTMGL1.003/2000.02.11/{tile_name}.SRTMGL1.hgt.zip",
                'output_name': f"n{lat:02d}_w{abs(lon):03d}_1arc_v3.tif"
            })
    
    logger.info(f"Generated {len(tiles)} tiles for USA coverage")
    return tiles

def download_and_convert_tile(tile):
    """Download and convert a single SRTM tile."""
    zip_path = TEMP_DIR / f"{tile['name']}.SRTMGL1.hgt.zip"
    hgt_path = TEMP_DIR / f"{tile['name']}.hgt"
    output_path = OUTPUT_DIR / tile['output_name']
    
    # Skip if already exists
    if output_path.exists():
        return {'success': True, 'tile': tile['name'], 'status': 'exists'}
    
    try:
        # Download with retry logic
        for attempt in range(RETRY_COUNT):
            try:
                cmd = [
                    'curl', '-f', '-L', '-n',
                    '-b', os.path.expanduser('~/.urs_cookies'),
                    '-c', os.path.expanduser('~/.urs_cookies'),
                    '-o', str(zip_path),
                    tile['url']
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if result.returncode == 0:
                    break
                else:
                    logger.warning(f"Download attempt {attempt + 1} failed for {tile['name']}: {result.stderr}")
                    if attempt == RETRY_COUNT - 1:
                        return {'success': False, 'tile': tile['name'], 'error': f"Download failed: {result.stderr}"}
                    time.sleep(2 ** attempt)  # Exponential backoff
            except subprocess.TimeoutExpired:
                logger.warning(f"Download timeout attempt {attempt + 1} for {tile['name']}")
                if attempt == RETRY_COUNT - 1:
                    return {'success': False, 'tile': tile['name'], 'error': "Download timeout"}
        
        # Extract
        extract_cmd = ['unzip', '-o', '-j', str(zip_path), '-d', str(TEMP_DIR)]
        result = subprocess.run(extract_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return {'success': False, 'tile': tile['name'], 'error': f"Extract failed: {result.stderr}"}
        
        # Convert HGT to GeoTIFF using rasterio
        convert_hgt_to_geotiff(hgt_path, output_path, tile['lat'], tile['lon'])
        
        # Cleanup temp files
        zip_path.unlink(missing_ok=True)
        hgt_path.unlink(missing_ok=True)
        
        return {'success': True, 'tile': tile['name'], 'status': 'downloaded'}
        
    except Exception as e:
        logger.error(f"Error processing {tile['name']}: {e}")
        return {'success': False, 'tile': tile['name'], 'error': str(e)}

def convert_hgt_to_geotiff(hgt_path, output_path, lat, lon):
    """Convert SRTM .hgt file to GeoTIFF format using rasterio."""
    import numpy as np
    from rasterio.transform import from_bounds
    
    # SRTM 1 arc-second files are 3601x3601 pixels covering exactly 1 degree
    width = height = 3601
    
    # Read the raw elevation data (16-bit big-endian signed integers)
    with open(hgt_path, 'rb') as f:
        data = np.frombuffer(f.read(), dtype='>i2')
    
    # Reshape to 2D array and convert to native endianness
    elevation = data.reshape(height, width).astype(np.int16)
    
    # Define the geospatial transform (SRTM data goes from NW to SE)
    transform = from_bounds(lon, lat, lon + 1, lat + 1, width, height)
    
    # Write as GeoTIFF with LZW compression
    with rasterio.open(
        output_path,
        'w',
        driver='GTiff',
        height=height,
        width=width,
        count=1,
        dtype='int16',
        crs='EPSG:4326',
        transform=transform,
        compress='lzw'
    ) as dst:
        dst.write(elevation, 1)

def main():
    """Main download orchestration."""
    print("🌍 NASA SRTM USA Download Started")
    print(f"📁 Output directory: {OUTPUT_DIR}")
    print(f"🔧 Workers: {MAX_WORKERS}")
    print()
    
    setup_directories()
    tiles = generate_tile_list()
    
    print(f"📦 Total tiles to process: {len(tiles)}")
    print("🚀 Starting download...")
    print()
    
    # Process tiles with progress bar
    success_count = 0
    error_count = 0
    exists_count = 0
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all download tasks
        future_to_tile = {executor.submit(download_and_convert_tile, tile): tile for tile in tiles}
        
        # Process results with progress bar
        with tqdm(total=len(tiles), desc="Processing tiles") as pbar:
            for future in as_completed(future_to_tile):
                result = future.result()
                
                if result['success']:
                    if result.get('status') == 'exists':
                        exists_count += 1
                    else:
                        success_count += 1
                else:
                    error_count += 1
                    logger.error(f"Failed: {result['tile']} - {result.get('error', 'Unknown error')}")
                
                pbar.update(1)
                pbar.set_postfix({
                    'Success': success_count,
                    'Exists': exists_count, 
                    'Errors': error_count
                })
    
    print()
    print("✅ Download Complete!")
    print(f"📊 Results: {success_count} downloaded, {exists_count} existing, {error_count} errors")
    print(f"📁 Files saved to: {OUTPUT_DIR}")
    
    # Cleanup temp directory
    if TEMP_DIR.exists():
        import shutil
        shutil.rmtree(TEMP_DIR)
    
    if error_count > 0:
        print(f"⚠️  {error_count} tiles failed - check logs for details")
        sys.exit(1)
    else:
        print("🎉 All tiles downloaded successfully!")

if __name__ == "__main__":
    main()