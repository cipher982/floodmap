#!/usr/bin/env python3
import math
from math import floor

def lat_lon_to_tile(lat, lon, zoom):
    n = 2.0**zoom
    xtile = int(floor((lon + 180.0) / 360.0 * n))
    ytile = int(floor((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n))
    return xtile, ytile

def tile_to_lat_lon(x, y, zoom):
    n = 2.0**zoom
    lon_deg = (x / n * 360.0) - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat_deg = math.degrees(lat_rad)
    return lat_deg, lon_deg

# Test SF coordinates
lat, lon = 37.7749, -122.4194
zoom = 9
print(f'Testing SF coordinates:')
print(f'Original: lat={lat}, lon={lon}, zoom={zoom}')

x, y = lat_lon_to_tile(lat, lon, zoom)
print(f'Tile: x={x}, y={y}')

lat_back, lon_back = tile_to_lat_lon(x, y, zoom)
print(f'Back: lat={lat_back}, lon={lon_back}')
print(f'Diff: lat={abs(lat-lat_back):.6f}, lon={abs(lon-lon_back):.6f}')

# Calculate tile size
n = 2 ** zoom
lon_per_tile = 360 / n
lat_per_tile = 170.1 / n
print(f'Tile size: lat={lat_per_tile:.6f}, lon={lon_per_tile:.6f}')
print(f'Diff as fraction of tile: lat={abs(lat-lat_back)/lat_per_tile:.3f}, lon={abs(lon-lon_back)/lon_per_tile:.3f}')