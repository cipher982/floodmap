#!/usr/bin/env python3
"""
Check if production has elevation data that's missing locally.
"""

import requests


def check_production_tile(x, y, z):
    """Check if production has elevation for a specific tile."""
    url = f"https://floodmap.drose.io/api/diagnostics/tile-debug?z={z}&x={x}&y={y}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return {
                "has_elevation": data.get("has_elevation", False),
                "overlapping_files": data.get("overlapping_files", 0),
                "roads_present": data.get("roads_present", False),
            }
    except Exception as e:
        print(f"Error checking tile ({x},{y},{z}): {e}")
    return None


def main():
    # Check the known problem tiles
    problem_tiles = [(569, 862, 11), (569, 863, 11)]

    print("Checking production elevation data for problem tiles:\n")

    for x, y, z in problem_tiles:
        print(f"Tile ({x},{y},{z}):")
        result = check_production_tile(x, y, z)
        if result:
            print(f"  Has elevation: {result['has_elevation']}")
            print(f"  Overlapping files: {result['overlapping_files']}")
            print(f"  Roads present: {result['roads_present']}")

            if result["has_elevation"]:
                print("  ✅ PRODUCTION HAS DATA (but local doesn't)")
            else:
                print("  ❌ Missing in production too")
        else:
            print("  ❓ Could not check production")
        print()


if __name__ == "__main__":
    main()
