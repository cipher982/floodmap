# DEM Data Gaps (“Blue polygons”, “No elevation data available”)

Symptoms:
- UI risk shows `No elevation data available (z11 sample)` or `Error retrieving elevation data`.
- Network shows elevation tiles returning NODATA (often very small brotli payloads; `content-length: 23` is a common all‑NODATA signature).

## Triage checklist
1. Capture: lat/lon + UI debug tile `z/x/y`.
2. Check precompressed tile headers:
   - `curl -I 'https://drose.io/floodmap/api/v1/tiles/elevation-data/z/x/y.u16?method=precompressed&v=XYZ' -H 'Accept-Encoding: br'`
3. Inside the webapp container, find the backing 1° source tile(s):
   - Use `elevation_loader.num2deg()` and `find_elevation_files_for_tile()`.
4. Inspect the source tile for large NoData regions (`-32768`) or legacy voids (`-32767`).

## Repair approach (point-of-origin)
Replace the 1° source DEM with a clean Skadi tile, then regenerate affected precompressed tiles.

Skadi URL pattern:
- `https://s3.amazonaws.com/elevation-tiles-prod/skadi/N33/N33W080.hgt.gz`

Safety:
- Back up the existing `.zst` + `.json` to:
  - `/mnt/backup/floodmap/data/elevation-source/repairs/`

After repair:
- Regenerate a small neighborhood of precompressed tiles around the affected `z/x/y` (don’t try to regen the world).
- Restart the webapp container if needed to flush in-process DEM caches.
- Bump the client `v=` cache key so users don’t stay pinned to old immutable tiles.
