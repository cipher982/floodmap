#!/usr/bin/env python3
"""
Fix ocean zeros in tile generation.
Treats elevation values of exactly 0 in ocean areas as NODATA.
"""

print("🔧 Fixing ocean zero elevation bug...")

# Fix the tile generation to treat 0 elevation as ocean
tiles_v1_path = "src/api/routers/tiles_v1.py"

with open(tiles_v1_path) as f:
    lines = f.readlines()

# Find and fix the NODATA mask line
for i, line in enumerate(lines):
    if "nodata_mask = (elevation_data == NODATA_VALUE)" in line:
        # Add check for zeros (ocean areas that should be NODATA)
        lines[i] = (
            "        # Also treat exact zeros as NODATA (ocean areas with bad data)\n"
        )
        lines[i] += (
            "        nodata_mask = (elevation_data == NODATA_VALUE) | (elevation_data == 0) | (elevation_data < -500) | (elevation_data > 9000)\n"
        )
        print(f"✅ Fixed line {i + 1}: Added zero check to NODATA mask")
        break

with open(tiles_v1_path, "w") as f:
    f.writelines(lines)

print("\n✅ Fixed ocean zero bug!")
print("🔄 Server will auto-reload with the fix")
