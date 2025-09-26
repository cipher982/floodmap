#!/usr/bin/env python3
"""
Trace exactly what happens during tile generation for broken coordinates.
"""

import sys

sys.path.append("/Users/davidrose/git/floodmap/src")

from pathlib import Path

import numpy as np
from PIL import Image

from api.color_mapping import color_mapper
from api.persistent_elevation_cache import PersistentElevationCache


def trace_tile_generation(z, x, y, water_level):
    """Trace step-by-step tile generation for debugging."""
    print(f"🔍 DIAGNOSTIC TRACE: Tile {z}/{x}/{y} at water level {water_level}m")
    print("=" * 70)

    # Step 1: Calculate tile bounds (from tiles.py logic)
    print("Step 1: Calculate tile bounds")
    n = 2.0**z
    lon_deg = x / n * 360.0 - 180.0
    lat_rad = np.arctan(np.sinh(np.pi * (1 - 2 * y / n)))
    lat_deg = np.degrees(lat_rad)

    lon_deg_next = (x + 1) / n * 360.0 - 180.0
    lat_rad_next = np.arctan(np.sinh(np.pi * (1 - 2 * (y + 1) / n)))
    lat_deg_next = np.degrees(lat_rad_next)

    lat_top = max(lat_deg, lat_deg_next)
    lat_bottom = min(lat_deg, lat_deg_next)
    lon_left = min(lon_deg, lon_deg_next)
    lon_right = max(lon_deg, lon_deg_next)

    print(
        f"   Bounds: lat {lat_bottom:.6f} to {lat_top:.6f}, lon {lon_left:.6f} to {lon_right:.6f}"
    )

    # Step 2: Find overlapping files
    print("\nStep 2: Find overlapping elevation files")
    elevation_path = Path("/Users/davidrose/git/floodmap/output/elevation")
    print(f"   Elevation path: {elevation_path}")
    print(f"   Path exists: {elevation_path.exists()}")

    if elevation_path.exists():
        elevation_files = list(elevation_path.glob("*.zst"))
        print(f"   Found {len(elevation_files)} elevation files:")
        for f in elevation_files[:5]:  # Show first 5
            print(f"      {f.name}")
        if len(elevation_files) > 5:
            print(f"      ... and {len(elevation_files) - 5} more")
    else:
        print("   ❌ Elevation path does not exist!")
        return

    # Step 3: Try to extract elevation data
    print("\nStep 3: Extract elevation data")
    persistent_cache = PersistentElevationCache()

    overlapping_files = []
    for file_path in elevation_files:
        # Parse filename format like "n29_w084_1arc_v3.zst"
        try:
            name = file_path.stem  # Remove .zst extension
            if name.startswith("n") and "_w" in name:
                # Extract lat/lon from format like "n29_w084_1arc_v3"
                parts = name.split("_")
                lat_part = parts[0]  # "n29"
                lon_part = parts[1]  # "w084"

                # Parse latitude (n29 -> 29.0)
                file_lat = float(lat_part[1:])  # Remove 'n', keep number

                # Parse longitude (w084 -> -84.0)
                file_lon = -float(lon_part[1:])  # Remove 'w', negate for west

                # Each SRTM file covers 1 degree, check if it overlaps tile bounds
                file_lat_max = file_lat + 1
                file_lat_min = file_lat
                file_lon_max = file_lon + 1
                file_lon_min = file_lon

                # Check for overlap
                lat_overlap = not (file_lat_max < lat_bottom or file_lat_min > lat_top)
                lon_overlap = not (file_lon_max < lon_left or file_lon_min > lon_right)

                if lat_overlap and lon_overlap:
                    overlapping_files.append(file_path)
                    print(
                        f"      MATCH: {name} covers lat {file_lat}-{file_lat_max}, lon {file_lon}-{file_lon_max}"
                    )
        except Exception as e:
            print(f"      Parse error for {file_path.name}: {e}")
            pass

    print(f"   Found {len(overlapping_files)} potentially overlapping files:")
    for f in overlapping_files:
        print(f"      {f.name}")

    # Step 4: Try extraction from each file
    print("\nStep 4: Attempt elevation data extraction")
    elevation_data = None
    extraction_log = []

    for file_path in overlapping_files:
        try:
            print(f"   Trying {file_path.name}...")
            data = persistent_cache.extract_tile_from_cached_array(
                file_path, lat_top, lat_bottom, lon_left, lon_right, 256
            )
            if data is not None:
                elevation_data = data
                print(f"   ✅ SUCCESS: Got data shape {data.shape}")
                print(f"   Data range: {np.min(data):.1f} to {np.max(data):.1f}m")
                print(f"   Data type: {data.dtype}")
                print(f"   Sample values: {data[128, 128]:.1f}m at center")
                break
            else:
                extraction_log.append(f"No data from {file_path.name}")
                print("   ⚠️  No data extracted")
        except Exception as e:
            extraction_log.append(f"Error from {file_path.name}: {e}")
            print(f"   ❌ Error: {e}")

    if elevation_data is None:
        print("\n🚨 CRITICAL: No elevation data extracted!")
        print("Extraction log:")
        for log in extraction_log:
            print(f"   {log}")
        return

    # Step 5: Color mapping
    print(f"\nStep 5: Apply color mapping (water level: {water_level}m)")
    rgba_data = color_mapper.elevation_array_to_rgba(elevation_data, water_level)
    print(f"   RGBA shape: {rgba_data.shape}")
    print(f"   RGBA dtype: {rgba_data.dtype}")

    # Analyze the colors
    unique_colors = np.unique(rgba_data.reshape(-1, 4), axis=0)
    print(f"   Unique colors: {len(unique_colors)}")

    if len(unique_colors) == 1:
        color = unique_colors[0]
        print(
            f"   🚨 SOLID COLOR: RGBA({color[0]}, {color[1]}, {color[2]}, {color[3]})"
        )

        # Check what this color represents
        if np.array_equal(color, color_mapper.FLOODED_COLOR):
            print("   This is FLOODED_COLOR - entire tile is below water level!")
        elif np.array_equal(color, color_mapper.SAFE_COLOR):
            print("   This is SAFE_COLOR - entire tile is above safe threshold!")
    else:
        print("   ✅ Color variation detected")
        for i, color in enumerate(unique_colors[:5]):
            print(
                f"      Color {i + 1}: RGBA({color[0]}, {color[1]}, {color[2]}, {color[3]})"
            )

    # Step 6: Create final tile
    print("\nStep 6: Generate PNG tile")
    img = Image.fromarray(rgba_data, mode="RGBA")

    # Save diagnostic tile
    diagnostic_path = f"diagnostic_tile_{z}_{x}_{y}_{water_level}.png"
    img.save(diagnostic_path)
    print(f"   Saved diagnostic tile: {diagnostic_path}")

    return {
        "bounds": (lat_top, lat_bottom, lon_left, lon_right),
        "overlapping_files": len(overlapping_files),
        "elevation_data": elevation_data is not None,
        "elevation_shape": elevation_data.shape if elevation_data is not None else None,
        "elevation_range": (np.min(elevation_data), np.max(elevation_data))
        if elevation_data is not None
        else None,
        "unique_colors": len(unique_colors),
        "is_solid": len(unique_colors) == 1,
        "diagnostic_path": diagnostic_path,
    }


def main():
    print("🚀 DIAGNOSTIC TRACE: Step-by-step tile generation")
    print("=" * 70)

    # Test the broken tile
    print("\n" + "=" * 70)
    print("BROKEN TILE ANALYSIS")
    broken_result = trace_tile_generation(8, 68, 106, 3.6)

    # Test a working tile for comparison
    print("\n" + "=" * 70)
    print("WORKING TILE ANALYSIS (for comparison)")
    working_result = trace_tile_generation(8, 68, 105, 3.6)

    # Summary comparison
    print("\n" + "=" * 70)
    print("COMPARISON SUMMARY")
    print("=" * 70)
    print("Broken tile (8/68/106):")
    print(f"   Overlapping files: {broken_result['overlapping_files']}")
    print(f"   Got elevation data: {broken_result['elevation_data']}")
    print(f"   Unique colors: {broken_result['unique_colors']}")
    print(f"   Is solid: {broken_result['is_solid']}")

    print("\nWorking tile (8/68/105):")
    print(f"   Overlapping files: {working_result['overlapping_files']}")
    print(f"   Got elevation data: {working_result['elevation_data']}")
    print(f"   Unique colors: {working_result['unique_colors']}")
    print(f"   Is solid: {working_result['is_solid']}")


if __name__ == "__main__":
    main()
