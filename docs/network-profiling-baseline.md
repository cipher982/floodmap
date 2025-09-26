Floodmap Network Profiling Baseline (2025‑09‑01)

Summary
- Goal: Measure real network cost of the live app first, then cut bytes/round‑trips surgically.
- Method: Black‑box HAR captures against https://floodmap.drose.io with consistent scenarios (cold, pan, zoom‑out, warm reload), stored and analyzed in‑repo.
- Outcome: Elevation tiles dominate transfer. Zoom‑out triggers double‑LOD fetches and large bursts. Immediate wins: enable Brotli/gzip on elevation and vector tiles, tighten low‑zoom vector generalization, and add strict client fetch scheduling.

Harness
- Location: tools/map-profiling
  - capture-har.mjs: Playwright HAR capture with pan/zoom/reload controls.
  - analyze-har.mjs: Totals, by type/host, largest resources (human output).
  - metrics.mjs: Machine‑readable JSON (totals, tiles by zoom, encodings).
  - profile-suite.mjs: Runs scenarios (cold, pan, zoomout, warm), persists HARs + metrics + summaries per run.
  - README.md: usage and outputs.
- How to run:
  - cd tools/map-profiling && npm i
  - Suite: URL=https://floodmap.drose.io npm run suite
  - Results: tools/map-profiling/results/<timestamp>/

Baseline Results
- Run: tools/map-profiling/results/20250901-152415
- Scenarios:
  - cold: 74 requests, 7.63 MB total
    - elevation: 46 tiles (6.05 MB); encoding: none; zoom: z=9
    - vector: 18 tiles (960 KB); encoding: zstd; zoom: z=8
  - pan: 76 requests, 7.62 MB total
    - elevation: 46 tiles (6.05 MB); encoding: none; z=9
    - vector: 20 tiles (955 KB); encoding: zstd; z=8
  - zoomout: 120 requests, 13.0 MB total
    - elevation: 85 tiles (11.2 MB); encoding: none; split across z=8 (~6.58 MB) and z=9 (~4.61 MB)
    - vector: 25 tiles (1.17 MB); encoding: zstd; z=6–8
  - warm (reload in same context): 119 requests, 13.6 MB total
    - elevation: 71 tiles (9.35 MB); encoding: none; z=9
    - vector: 27 tiles (2.29 MB); encoding: zstd; z=8

Key Findings
- Elevation tiles are raw 16‑bit binary (.u16) with no Content‑Encoding; each tile ≈128 KiB. These dominate total transfer, especially during zoom changes.
- Zoom‑out multiplies elevation requests (double LOD) and increases vector tiles across multiple zooms → bytes per viewport are not bounded at low zooms.
- Vector tiles (.pbf) are transferred with Content‑Encoding: zstd. Individual tiles at low zoom are ~165–295 KB; stronger generalization likely needed.
- Client‑side caching makes “second load faster,” but server‑side behavior across fresh contexts shows similar transfer; improvements should target compression and LOD.

Header/Encoding Observations
- Elevation (.u16): Cache‑Control: public, max‑age=31536000, immutable; Content‑Encoding: (none). Good cache headers, but missing compression.
- Vector (.pbf): Cache‑Control: public, max‑age=31536000, immutable; Content‑Encoding: zstd; client Accept‑Encoding includes br, gzip, zstd.

Compressibility Tests (local samples)
- Elevation .u16 (131,072 bytes):
  - br (q11): ~25–28 KiB (≈80% reduction)
  - gzip -9: ~32 KiB (≈75% reduction)
- Vector .pbf (286,103 bytes sample):
  - br (q11): ~180 KiB (≈37% reduction)
  - gzip -9: ~192 KiB (≈33% reduction)

Interpretation
- Elevation compression is a high‑leverage change: enabling Content‑Encoding for .u16 would reduce the largest contributor immediately without changing client code.
- Zoom transitions fetch tiles for both source and target zooms; without strict abort/concurrency controls and LOD gating, zoom‑out floods the network.
- Vector tiles at low zoom have room for size reductions via simplification and attribute pruning.

Prioritized Actions (Top 5)
1) Elevation Compression (br/gzip)
   - Impact: ~60–80% reduction on DEM bytes; minimal code changes (server config or static precompression).
2) Fetch Scheduling (client)
   - Cap concurrency (6–8); AbortController on zoom/pan; reduce low‑zoom prefetch and cross‑fade windows.
3) Vector Generalization (low zoom)
   - Increase simplification; drop minor layers/attrs at z≤8; target ≤100 KB avg per tile.
4) Vector Brotli
   - Serve .pbf.br (or dynamic br) where clients advertise br; reduces payload ~30–40% over current zstd sample.
5) DEM LOD Pyramid
   - Serve coarser elevation grids at low zoom (e.g., 32×32 / 64×64) to stabilize bytes per viewport and speed decode.

Proposed Validation Loop
1) Run suite (cold, pan, zoomout, warm) → persist results.
2) Apply one change (e.g., enable br for .u16) → re‑run suite → compare summaries.
3) Iterate through top 5 changes; compile a before/after table.

How To Re‑Run
- cd tools/map-profiling && npm i
- URL=https://floodmap.drose.io npm run suite
- Inspect results in tools/map-profiling/results/<timestamp>/summary.md and summary.json.

Notes & Lessons Learned
- Black‑box profiling is effective even without code access; the harness is now versioned here for repeatability.
- Elevation payloads dominate; compression and LOD deliver outsized wins with low risk.
- Zoom‑out stress is primarily double‑LOD + lack of aggressive cancellation; fixable on the client regardless of server.

Appendix: Files Added
- tools/map-profiling/* (harness + suite + example results)
