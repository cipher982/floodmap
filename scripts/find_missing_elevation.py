#!/usr/bin/env python3
"""
Find tiles that have vector data (roads) but missing elevation data.
This identifies the exact problem areas shown in the UI.
"""
import sys
from pathlib import Path
import asyncio

# Add src/api to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'api'))

from elevation_loader import elevation_loader

async def check_tile_has_roads(x, y, z):
    """Check if a tile has vector/road data."""
    try:
        return await elevation_loader._check_vector_tile(x, y, z)
    except Exception:
        return False

def check_tile_has_elevation(x, y, z):
    """Check if a tile has elevation data."""
    try:
        arr = elevation_loader.get_elevation_for_tile(x, y, z, tile_size=256)
        return arr is not None
    except Exception:
        return False

async def find_problem_tiles(z=11, florida_bbox=True):
    """Find tiles with roads but no elevation in Florida area."""
    if florida_bbox:
        # Focus on Florida east coast where the problem is visible
        min_lon, min_lat, max_lon, max_lat = -82.0, 25.0, -79.0, 29.0
    else:
        # Wider search
        min_lon, min_lat, max_lon, max_lat = -85.0, 24.0, -75.0, 31.0
    
    # Convert bbox to tile coordinates
    import math
    def deg2num(lat_deg, lon_deg, zoom):
        lat_rad = math.radians(lat_deg)
        n = 2.0 ** zoom
        xtile = int((lon_deg + 180.0) / 360.0 * n)
        ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        return xtile, ytile

    x_min, y_max = deg2num(min_lat, min_lon, z)
    x_max, y_min = deg2num(max_lat, max_lon, z)
    x0, x1 = min(x_min, x_max), max(x_min, x_max)
    y0, y1 = min(y_min, y_max), max(y_min, y_max)
    
    print(f"Scanning zoom {z}, tiles x={x0}-{x1}, y={y0}-{y1}")
    print("Looking for tiles with roads but no elevation...\n")
    
    problem_tiles = []
    total_checked = 0
    
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            total_checked += 1
            
            # Check elevation first (faster)
            has_elevation = check_tile_has_elevation(x, y, z)
            
            if not has_elevation:
                # Only check roads if no elevation
                has_roads = await check_tile_has_roads(x, y, z)
                
                if has_roads:
                    # Get tile bounds for reference
                    lat_top, lat_bottom, lon_left, lon_right = elevation_loader.num2deg(x, y, z)
                    problem_tiles.append({
                        'x': x, 'y': y, 'z': z,
                        'lat_range': f"{lat_bottom:.3f} to {lat_top:.3f}",
                        'lon_range': f"{lon_left:.3f} to {lon_right:.3f}"
                    })
                    print(f"PROBLEM TILE: ({x},{y},{z}) - lat {lat_bottom:.3f}-{lat_top:.3f}, lon {lon_left:.3f}-{lon_right:.3f}")
    
    print(f"\n=== SUMMARY ===")
    print(f"Total tiles checked: {total_checked}")
    print(f"Problem tiles found: {len(problem_tiles)}")
    print(f"These tiles have roads/vectors but no elevation data")
    
    return problem_tiles

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Find tiles with roads but no elevation")
    parser.add_argument('--zoom', '-z', type=int, default=11, help='Zoom level to check')
    parser.add_argument('--wide', action='store_true', help='Check wider area beyond Florida')
    
    args = parser.parse_args()
    
    asyncio.run(find_problem_tiles(z=args.zoom, florida_bbox=not args.wide))