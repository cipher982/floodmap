#!/usr/bin/env python3
"""
Simple tile generator for Tampa elevation data using existing libraries.
Creates basic PNG tiles for zoom levels 10-14 without requiring GDAL.
"""

import os
import math
import numpy as np
from PIL import Image, ImageDraw
import rasterio
from rasterio.transform import from_bounds
import logging

logging.basicConfig(level=logging.INFO)

# Configuration
INPUT_DIR = "scratch/data_tampa"
OUTPUT_DIR = "scratch/data_tampa_processed"
ZOOM_LEVELS = [10, 11, 12]  # Start with lower levels for speed

def deg2num(lat_deg, lon_deg, zoom):
    """Convert lat/lon to tile numbers"""
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (xtile, ytile)

def num2deg(xtile, ytile, zoom):
    """Convert tile numbers to lat/lon bounds"""
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return (lat_deg, lon_deg)

def get_tile_bounds(xtile, ytile, zoom):
    """Get the bounding box for a tile"""
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    
    lon_deg_max = (xtile + 1) / n * 360.0 - 180.0
    lat_rad_max = math.atan(math.sinh(math.pi * (1 - 2 * (ytile + 1) / n)))
    lat_deg_max = math.degrees(lat_rad_max)
    
    return (lon_deg, lat_deg_max, lon_deg_max, lat_deg)  # west, north, east, south

def elevation_to_color(elevation):
    """Convert elevation to RGB color"""
    if elevation is None or np.isnan(elevation):
        return (0, 0, 0, 0)  # Transparent for no data
    
    # Normalize elevation to 0-255 range
    # Tampa area roughly 0-100m elevation
    normalized = max(0, min(255, int(elevation * 2.5)))
    
    # Create color gradient: blue (low) -> green -> yellow -> red (high)
    if normalized < 64:
        # Blue to green
        r = 0
        g = normalized * 4
        b = 255 - normalized * 2
    elif normalized < 128:
        # Green to yellow
        r = (normalized - 64) * 4
        g = 255
        b = 0
    elif normalized < 192:
        # Yellow to orange
        r = 255
        g = 255 - (normalized - 128) * 2
        b = 0
    else:
        # Orange to red
        r = 255
        g = max(0, 128 - (normalized - 192) * 2)
        b = 0
    
    return (r, g, b, 180)  # Semi-transparent

def create_tile(xtile, ytile, zoom, tif_data, tif_bounds, tif_transforms):
    """Create a single tile"""
    # Get tile bounds
    west, north, east, south = get_tile_bounds(xtile, ytile, zoom)
    
    # Create 256x256 image
    img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    pixels = img.load()
    
    # Sample elevation data across the tile
    for py in range(256):
        for px in range(256):
            # Convert pixel to lat/lon
            lon = west + (px / 256.0) * (east - west)
            lat = north + ((255 - py) / 256.0) * (south - north)
            
            # Find elevation at this point
            elevation = None
            for i, bounds in enumerate(tif_bounds):
                if (bounds.left <= lon <= bounds.right and 
                    bounds.bottom <= lat <= bounds.top):
                    
                    # Convert lat/lon to array indices
                    transform = tif_transforms[i]
                    col = int((lon - transform.c) / transform.a)
                    row = int((lat - transform.f) / transform.e)
                    
                    # Check bounds
                    data = tif_data[i]
                    if 0 <= row < data.shape[0] and 0 <= col < data.shape[1]:
                        elev_val = data[row, col]
                        if not np.isnan(elev_val) and elev_val != -32768:  # No data value
                            elevation = float(elev_val)
                            break
            
            if elevation is not None:
                color = elevation_to_color(elevation)
                pixels[px, py] = color
    
    return img

def generate_tiles():
    """Generate tiles for all zoom levels"""
    # Load TIF data
    tif_files = [f for f in os.listdir(INPUT_DIR) if f.endswith('.tif')]
    if not tif_files:
        logging.error(f"No TIF files found in {INPUT_DIR}")
        return
    
    tif_data = []
    tif_bounds = []
    tif_transforms = []
    
    logging.info(f"Loading {len(tif_files)} TIF files...")
    for tif_file in tif_files:
        filepath = os.path.join(INPUT_DIR, tif_file)
        with rasterio.open(filepath) as src:
            data = src.read(1)
            bounds = src.bounds
            transform = src.transform
            
            tif_data.append(data) 
            tif_bounds.append(bounds)
            tif_transforms.append(transform)
            logging.info(f"Loaded {tif_file}: {data.shape}")
    
    # Tampa area bounds (approximate)
    tampa_bounds = {
        'west': -83.0,
        'east': -82.0, 
        'north': 28.5,
        'south': 27.5
    }
    
    total_tiles = 0
    
    for zoom in ZOOM_LEVELS:
        logging.info(f"Generating zoom level {zoom}...")
        
        # Calculate tile range for Tampa area
        x_min, y_north = deg2num(tampa_bounds['north'], tampa_bounds['west'], zoom)
        x_max, y_south = deg2num(tampa_bounds['south'], tampa_bounds['east'], zoom)
        
        # y coordinates are flipped in tile system
        y_min = min(y_north, y_south)
        y_max = max(y_north, y_south)
        
        logging.info(f"Zoom {zoom}: x_range=({x_min}, {x_max}), y_range=({y_min}, {y_max})")
        
        zoom_dir = os.path.join(OUTPUT_DIR, str(zoom))
        
        tiles_this_zoom = 0
        for xtile in range(x_min, x_max + 1):
            x_dir = os.path.join(zoom_dir, str(xtile))
            os.makedirs(x_dir, exist_ok=True)
            
            for ytile in range(y_min, y_max + 1):
                tile_path = os.path.join(x_dir, f"{ytile}.png")
                
                # Create the tile
                img = create_tile(xtile, ytile, zoom, tif_data, tif_bounds, tif_transforms)
                img.save(tile_path, "PNG")
                
                tiles_this_zoom += 1
                total_tiles += 1
        
        logging.info(f"Generated {tiles_this_zoom} tiles for zoom {zoom}")
    
    logging.info(f"Total tiles generated: {total_tiles}")

if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    generate_tiles()