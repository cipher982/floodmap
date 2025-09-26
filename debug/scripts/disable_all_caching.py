#!/usr/bin/env python3
"""
NUCLEAR OPTION: Disable ALL caching everywhere
This is for debugging only - will make the app very slow but predictable
"""

print("🔥 DISABLING ALL CACHING LAYERS...")

# 1. Modify tile_cache.py to have TTL of 0
print("1. Disabling tile cache...")
tile_cache_path = "src/api/tile_cache.py"
with open(tile_cache_path) as f:
    content = f.read()

# Replace TTL with 0 seconds (instant expiry)
content = content.replace(
    "cache_ttl = 60 if IS_DEVELOPMENT else TILE_CACHE_TTL",
    "cache_ttl = 0  # DISABLED FOR DEBUGGING",
)
content = content.replace(
    "self.ttl_seconds = ttl_seconds or float('inf')",
    "self.ttl_seconds = 0  # DISABLED FOR DEBUGGING",
)

with open(tile_cache_path, "w") as f:
    f.write(content)

# 2. Disable persistent elevation cache
print("2. Disabling persistent elevation cache...")
elevation_cache_path = "src/api/persistent_elevation_cache.py"
with open(elevation_cache_path) as f:
    content = f.read()

# Make cache always miss by setting max memory to 0
content = content.replace(
    "persistent_elevation_cache = PersistentElevationCache(max_memory_gb=4.0)",
    "persistent_elevation_cache = PersistentElevationCache(max_memory_gb=0.0)  # DISABLED FOR DEBUGGING",
)

with open(elevation_cache_path, "w") as f:
    f.write(content)

# 3. Add no-cache headers to tiles_v1.py
print("3. Adding no-cache headers to all tile responses...")
tiles_path = "src/api/routers/tiles_v1.py"
with open(tiles_path) as f:
    lines = f.readlines()

# Find all Response returns and add no-cache headers
for i, line in enumerate(lines):
    if "return Response(" in line and "headers=" not in line:
        # Add no-cache headers to the response
        lines[i] = (
            line.rstrip()
            + """
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0"
        })
"""
        )

with open(tiles_path, "w") as f:
    f.writelines(lines)

# 4. Add aggressive cache busting to client
print("4. Adding aggressive cache-busting to client...")
client_path = "src/web/js/elevation-renderer.js"
with open(client_path) as f:
    content = f.read()

# Force cache busting on EVERY request
content = content.replace(
    "const cacheBuster = window.location.hostname === 'localhost' ? `?t=${Date.now()}` : '';",
    "const cacheBuster = `?t=${Date.now()}&r=${Math.random()}`;  // AGGRESSIVE CACHE BUSTING",
)

with open(client_path, "w") as f:
    f.write(content)

# Also update map-client.js
map_client_path = "src/web/js/map-client.js"
with open(map_client_path) as f:
    content = f.read()

# Add timestamp to tile URLs
content = content.replace(
    "return 'client://elevation/{z}/{x}/{y}';",
    "return `client://elevation/{z}/{x}/{y}?t=${Date.now()}`;  // CACHE BUSTING",
)
content = content.replace(
    "return 'client://flood/{z}/{x}/{y}';",
    "return `client://flood/{z}/{x}/{y}?t=${Date.now()}`;  // CACHE BUSTING",
)

with open(map_client_path, "w") as f:
    f.write(content)

print("\n✅ ALL CACHING DISABLED!")
print("\n⚠️  WARNING: The app will be VERY SLOW now")
print("⚠️  This is for debugging only!")
print("\n📝 To restore normal caching, run:")
print("   git checkout src/api/tile_cache.py")
print("   git checkout src/api/persistent_elevation_cache.py")
print("   git checkout src/api/routers/tiles_v1.py")
print("   git checkout src/web/js/elevation-renderer.js")
print("   git checkout src/web/js/map-client.js")
print("\n🔄 Now restart the server with: make restart")
