#!/usr/bin/env python3
"""
Convert SRTM .hgt files to GeoTIFF format.
"""
import sys
import rasterio
import numpy as np
from pathlib import Path

def convert_hgt_to_geotiff(hgt_path, output_path, lat, lon):
    """Convert HGT file to GeoTIFF."""
    hgt_file = Path(hgt_path)
    
    # Read HGT file as binary
    with open(hgt_file, 'rb') as f:
        data = f.read()
    
    # SRTM 1 arc-second is 3601x3601 pixels
    size = int(np.sqrt(len(data) // 2))
    
    # Convert to numpy array (big-endian 16-bit signed integers)
    elevation = np.frombuffer(data, dtype='>i2').reshape(size, size)
    
    # Calculate geotransform (pixel coordinates to geographic)
    # SRTM tiles are 1 degree x 1 degree
    pixel_size = 1.0 / (size - 1)
    
    # Upper left corner coordinates
    ul_lon = lon
    ul_lat = lat + 1
    
    transform = rasterio.transform.from_bounds(
        ul_lon, lat, lon + 1, ul_lat, size, size
    )
    
    # Write GeoTIFF
    with rasterio.open(
        output_path,
        'w',
        driver='GTiff',
        height=size,
        width=size,
        count=1,
        dtype='int16',
        crs='EPSG:4326',
        transform=transform,
        compress='lzw'
    ) as dst:
        dst.write(elevation, 1)
    
    print(f"Converted {hgt_file} to {output_path}")

if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage: python convert_hgt.py <hgt_file> <output_tif> <lat> <lon>")
        sys.exit(1)
    
    hgt_path = sys.argv[1]
    output_path = sys.argv[2] 
    lat = int(sys.argv[3])
    lon = int(sys.argv[4])
    
    convert_hgt_to_geotiff(hgt_path, output_path, lat, lon)