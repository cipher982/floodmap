# CONUS HAND Refactor Spec

Status: Phase 3 follow-up review pending
Owner: Codex
Baseline commit: `1865fd4 Add Birmingham HAND prototype`

## Goal

Build a whole-USA terrain-risk map using HAND-style height above downstream
drainage. The product must be national, inspectable, and honest:

- The main value is "how close is this land to its local drainage path", not sea
  level.
- The slider remains useful inland because it thresholds HAND values, not
  absolute elevation.
- The national architecture must fit normal object storage and a small VPS/API
  service. It must not depend on committing national data to git.

## Non-goals

- Do not model rainfall, storm sewers, culvert blockage, return periods, FEMA
  zones, or real-time forecast inundation.
- Do not use generative AI to sharpen or invent the risk layer.
- Do not precompute every national z14/z15 rendered PNG. The user needs an
  interactive national map, not a static image archive.

## Data Sources

Primary national input target:

- NHDPlus HR / successor 3DHP hydrography and raster products.
- 10m 3DEP-derived terrain where available.

USGS describes NHDPlus HR as built from high-resolution NHD, 10m 3DEP, and WBD.
It includes flow direction, flow accumulation, elevation, hydro-enforced
elevation rasters, catchments, and stream-network attributes. That is the right
family of source data for this product.

Reference URLs:

- `https://www.usgs.gov/national-hydrography/nhdplus-high-resolution`
- `https://pubs.usgs.gov/publication/sir20255031/full`
- `https://gdal.org/en/stable/drivers/raster/cog.html`

## Storage Reality

Reproducible estimator:

```bash
uv run python tools/hand/storage_estimator.py --max-zoom 14
```

Current outputs:

| Shape | Max zoom | Raw `.u16` web-tile storage |
|---|---:|---:|
| CONUS bbox | z14 | 687.3 GB |
| Alaska bbox | z14 | 685.1 GB |
| Hawaii bbox | z14 | 11.0 GB |
| Puerto Rico/VI bbox | z14 | 1.7 GB |
| All listed bboxes | z14 | 1.385 TB |

Source-raster order of magnitude:

| Source model | Raw | Raw + overviews |
|---|---:|---:|
| CONUS 10m uint16 HAND | 161.6 GB | 215.5 GB |
| All-US 10m uint16 HAND | 196.6 GB | 262.1 GB |
| CONUS 30m uint16 HAND | 18.0 GB | 23.9 GB |
| All-US 30m uint16 HAND | 21.8 GB | 29.1 GB |

Measured local Birmingham artifact:

- Static z9-z12 `.u16` tiles: 73 tiles, 9.6 MB raw.
- Birmingham z9-z14 bbox estimate: 866 tiles, about 113.5 MB raw.

Conclusion:

- z12/z13 national static tiles are feasible but still should live outside git.
- z14 national static tiles are storage-feasible in object storage, but clumsy
  as a primary source and expensive to rebuild.
- z15 national static tiles are not a sensible first product for 10m source data.
- The primary national representation should be source HAND rasters, with web
  tiles rendered and cached from them.
- Bbox tile counts are ceilings. Land clipping, NODATA tiles, and Brotli should
  reduce actual persisted tile storage. Do not use raw bbox counts as a bill.
- Source-raster raw + overview estimates are also ceilings before COG compression
  and predictor/delta effects.

## Architecture Decision

Use a two-tier data architecture:

1. Source layer: compressed, tiled source rasters storing HAND in uint16
   decimeters or centimeters, nodata `65535`.
2. Delivery layer: `.u16` web tiles served to the browser, compressed with
   Brotli/gzip, rendered client-side by the same pattern as the current elevation
   layer.

Do not make threshold-specific PNG tiles. The slider should update client-side
from cached raw HAND values.

Recommended source format:

- COG per region/VPU/HU4 or packed COG mosaic manifest.
- Internal tiling, overviews, compression, and a stable manifest.
- Read with rasterio/GDAL locally first; keep the path object-storage compatible.
- Keep source rasters in their hydrologic/native projected CRS at rest. Reproject
  to Web Mercator per requested web tile. This preserves the compute model and
  avoids baking Web Mercator distortion into the source product.

Initial manifest schema:

```json
{
  "schema_version": 1,
  "dataset_version": "hand-YYYYMMDDa",
  "layers": {
    "hand": {
      "encoding": "uint16-decimeters",
      "nodata": 65535,
      "regions": [
        {
          "id": "birmingham-prototype",
          "bbox": [-87.02, 33.3, -86.52, 33.75],
          "crs": "EPSG:5070",
          "url": "file://data/terrain/hand/birmingham-prototype.cog.tif"
        }
      ]
    }
  }
}
```

Recommended delivery cache:

- Precompute z9-z12 nationally for fast map open.
- Optionally precompute z13 after the pipeline proves stable.
- Render z14 on demand from source rasters and persist hot tiles.
- Budget cache explicitly: 100 GB MVP, 500 GB serious demo, 1-2 TB production-ish.

## API Shape

Add a generic terrain tile surface instead of hardcoding Birmingham:

```text
GET /api/v2/terrain/{layer}/{dataset_version}/{z}/{x}/{y}.u16
POST /api/v2/terrain/{layer}/{dataset_version}/batch.u16
GET /api/v2/terrain/{layer}/sample?lat=...&lng=...
GET /api/v2/terrain/{layer}/metadata
```

Initial layers:

- `elevation`: existing absolute elevation data, compatibility target.
- `hand`: height above downstream drainage.

The v2 implementation should support:

- source manifests
- precomputed tile lookup
- dynamic source-raster render fallback
- Brotli/gzip negotiation
- short-cache misses, immutable hits
- local source paths now, object-storage paths later
- immutable cache keys via `dataset_version` in the URL path

Miss semantics:

- If a tile has source coverage and the source pixels are NODATA, return a normal
  NODATA `.u16` tile with immutable cache headers.
- If a precomputed tile is absent but source coverage exists, dynamically render
  and optionally populate cache.
- If source coverage is absent or the dataset is not built yet, return 404 or 503
  with short/no-cache headers. Do not silently return a long-lived NODATA tile for
  a build miss.

## Client Shape

Refactor the map client so "raster value layer" is generic:

- Fetch raw `.u16` data.
- Decode to typed arrays.
- Render with a mode-specific LUT.
- Decode values with a mode-specific decoder. Existing elevation values encode
  `-500..9000m`; HAND values encode drainage-relative height and must not reuse
  the elevation decoder.
- Existing `elevation` and new `hand` modes share request/cache plumbing.

HAND display:

- Slider label: `Height above local drainage`.
- Value units: feet for UI, meters internally.
- Transparent above threshold.
- Hard low band for `0-1 ft`.
- Optional deterministic display smoothing only if clearly labeled as display
  generalization.

## MVP Validation

### MVP A: Storage estimator

Already implemented:

- `tools/hand/storage_estimator.py`
- `tests/unit/test_hand_storage_estimator.py`

Acceptance:

- Birmingham z9-z12 estimator matches generated artifact counts.
- CONUS z14 raw estimate is pinned by unit test.
- CLI prints national web-tile and source-raster budgets.

### MVP B: Source-raster dynamic render

Build next:

- Generate a Birmingham HAND source COG from the existing algorithm.
- Render `/api/v2/terrain/hand/{dataset_version}/{z}/{x}/{y}.u16` dynamically
  from that source COG.
- Compare dynamic tile values against current static Birmingham `.u16` tiles for
  at least three z12 tiles and one clicked sample.
- Measure local-disk dynamic render latency.

Acceptance:

- Dynamic tile returns 131072 bytes.
- Dynamic source render p50 under 150ms and p95 under 300ms for sampled z12-z14
  tiles on local disk; hot-cache p95 under 50ms.
- Dynamic sample grid across at least 25 Birmingham points has p95 absolute
  difference under 0.5 ft versus static prototype tiles.
- Browser can render the dynamic layer without static prototype tile files.
- Dynamic route reports cache/source headers clearly enough to distinguish
  source NODATA from build miss.

Measured Phase 3 result:

- Validation command:
  `uv run --with rasterio --with affine python tools/hand/validate_birmingham_dynamic.py`
- Dynamic-vs-static tile comparison across all 73 committed Birmingham prototype
  tiles: p50/p95/max absolute difference `0.00 / 0.00 / 0.00 ft` where both
  sources have data.
- NODATA mismatch: `994` pixels, `0.0208%` of compared pixels.
- Local dynamic render p50/p95: `27.0 / 60.0 ms`; hot in-memory cache p95
  rounds to `0.0 ms`.
- Downtown direct source sample returns `25.3 ft`; the old z12 static-tile sample
  returns `24.3 ft` because it samples the rendered web tile pixel, not the exact
  source raster point.
- The route is gated by `TERRAIN_V2_ENABLED` until the serving image includes
  the geospatial runtime dependencies needed for dynamic COG reads.

### MVP C: Second geography smoke

Build after MVP B:

- Run the same generator for one non-Birmingham watershed/metro bbox.
- Do not add that artifact to git.
- Record: DEM size, selected flowline count, source COG size, dynamic tile
  latency, and visual screenshot.

Acceptance:

- The dynamic renderer works without Birmingham-specific paths.
- The map shows drainage-relative corridors in a second geography.
- Failure modes are documented if the source data is sparse or noisy.

## Full CONUS Build Plan

### Phase 1: Plan and estimator

Deliverables:

- This spec.
- Storage estimator and tests.
- Opus plan review before architecture edits.

Commit after review.

### Phase 2: Generic terrain source abstraction

Deliverables:

- Terrain source manifest model.
- `.u16` tile encode/decode helpers shared by elevation/HAND code.
- Versioned terrain tile URL contract.
- v2 batch format decision: keep parity with existing batch fetches by supporting
  batch `.u16` for both `elevation` and `hand`.
- Unit tests for tile coordinate math, encoding, nodata, and compression headers.

Opus review after commit.

### Phase 3: Dynamic COG tile renderer

Deliverables:

- COG-backed `hand` source for Birmingham.
- `/api/v2/terrain/hand/{dataset_version}/{z}/{x}/{y}.u16`.
- `/sample` and `/metadata`.
- Equivalence tests against committed Birmingham static tiles.
- Local-disk dynamic render latency measurements.
- In-memory hot tile cache on the dynamic path.

Opus review after commit.

### Phase 4: Persistent tile cache and precompute CLI

Deliverables:

- File/object-store layout for precomputed `.u16.br` tiles.
- Dynamic render fallback writes hot cache entries.
- CLI to precompute z9-z12 for a manifest region.
- Cache budget reporting.
- Tile requests must route by tile/region intersection, not by the first
  manifest region.
- Outside-coverage tiles must remain short-cache 404/503 misses, never immutable
  NODATA.
- Persistent cache design should replace the in-memory per-process LRU for
  cross-worker reuse.

Opus review after commit.

### Phase 5: Client raster-value refactor

Deliverables:

- Main map can switch between elevation, old flood view, and HAND.
- Shared typed-array cache and worker path.
- Mode-specific decode and worker LUT cache keys.
- Birmingham source can be enabled behind config while national data is absent.
- Existing elevation layer can be served through v2 and matches v1 tile bytes for
  a sample grid before any v1 deprecation.
- Browser smoke with Playwright screenshots.
- Bump `ASSET_VERSION` in `src/api/page_renderer.py` for JS/CSS/worker changes.

Opus review after commit.

### Phase 6: CONUS builder design

Deliverables:

- VPU/HU4 job manifest.
- Runnable dry-run that emits a manifest for at least two representative regions.
- Download/verify stage for NHDPlus HR/3DHP inputs.
- HAND compute stage per region.
- Source COG output stage.
- Overview-aware source reads or precomputed low-zoom tiles so national z9-z12
  requests do not read native-resolution 10m windows.
- QA metrics per region: valid cells, nodata cells, flowline counts, percentile
  HAND values, sample images.

Opus review before any large compute.

### Phase 7: CONUS pilot compute

Deliverables:

- Run 2-3 representative regions, not just one city.
- Measure runtime, disk, COG compression, z12/z14 tile latency.
- Revise storage budget from measured data.

Opus review after pilot.

### Phase 8: National rollout

Deliverables:

- Batch compute all CONUS regions.
- Publish source manifest.
- Precompute z9-z12.
- Enable dynamic z13/z14 cache.
- Production smoke and network profile.

Opus review before public launch copy is updated.

## Commit/Review Protocol

- Commit each phase separately.
- No `--no-verify`.
- Hatch Opus reviews the plan before Phase 2 starts.
- Hatch Opus reviews each implementation phase after tests pass and before the
  next phase begins.
- If Opus finds a blocker, fix and request focused follow-up review.

## Risks

- NHDPlus HR is not the future-maintained dataset everywhere; 3DHP migration
  may change inputs.
- Alaska and territories have different coverage/projection/data quality.
- HAND is not pluvial flooding. Copy must stay clear.
- Culverts, storm drains, road embankments, and local obstructions will remain
  imperfect at 10m.
- Object storage and caching are product requirements, not optional optimizations.

## Current Recommendation

Proceed with Phase 2 only after Opus approves this plan. The national product is
storage-feasible if source rasters are the canonical dataset and web tiles are a
cache, not the only representation.
