# HAND MVP Next Steps

Status: Opus reviewed; execution gates set
Owner: Codex

## Current Position

Floodmap now has a two-region HAND-style drainage MVP:

- Birmingham prototype region.
- Houston bayou pilot region.
- Manifest-driven terrain v2 API serving uint16-decimeter HAND tiles from COGs.
- Browser-side slider rendering for height above nearby mapped drainage.
- Cube Tailscale review stack for end-to-end QA.

This is enough to evaluate the product direction, but not enough to scale to
CONUS yet. The next work should prove that the demo is reproducible, readable,
and externally defensible before expanding data volume.

## Iteration Gates

### Gate 1: Reproducible Cube Runtime

Goal: restarting the review stack must not depend on remembered shell history.

Success criteria:

- `scripts/cube-review-up.sh` starts tileserver-gl and FastAPI on Cube.
- Runtime env is explicit:
  - `FLOODMAP_DATA_ROOT=/mnt/storage/floodmap/data`
  - `TERRAIN_MANIFEST_PATH=/mnt/storage/floodmap/data/terrain/manifest.json`
  - `TERRAIN_V2_ENABLED=true`
  - `TILESERVER_URL=http://100.125.140.78:18080`
  - `TERRAIN_CACHE_MAX_BYTES=21474836480`
- Script refuses to use paths under `/mnt/gemini`.
- Vector tile proxy returns `200` for a known Birmingham tile.
- HAND metadata returns `200`.
- HAND sample returns non-null height for downtown Birmingham.
- Browser smoke sees at least one rendered road feature in `hand` mode.

Result:

- Complete on `2026-05-14`.
- `make cube-review` restarts tileserver-gl and FastAPI with the required env.
- Script smoke checks pass for vector tiles, HAND metadata, HAND sample, and a
  Birmingham HAND tile.
- Browser smoke in `hand` mode saw `128` rendered road features and `10`
  rendered waterway features.

### Gate 2: Basemap Readability

Goal: screenshots should look like a real street map with a HAND overlay, not a
white engineering canvas with thin road lines.

Success criteria:

- Roads vary by class instead of one universal 1px stroke.
- Place labels are visible at city/neighborhood zooms.
- Road labels are visible by z11/z12 where OpenMapTiles data supports them.
- Water/park/landuse context does not overpower the HAND overlay.
- Browser screenshot at Birmingham z11 shows readable street-map context.

Result:

- Complete on `2026-05-14` for the Cube review MVP.
- Asset version `20260514d` adds road hierarchy, place labels, road labels,
  waterway labels, park labels, and light landcover/landuse context.
- Browser smoke at Birmingham z11 counted:
  - `128` road features.
  - `17` road label features.
  - `26` place label features.
  - `1` waterway label feature.
  - `2` park label features.
- Caveat: labels currently use MapLibre's demo glyph endpoint. Self-host glyphs
  before public production launch.

### Gate 3: External Reference Comparison

Goal: the product story should be defensible against at least one independent
flood reference, even if the comparison is imperfect.

Success criteria:

- A script compares HAND threshold masks against one external reference dataset
  for Birmingham and Houston.
- Report records IoU, confusion counts, and coverage percentage at 3ft, 6ft,
  and 10ft thresholds.
- The result is documented plainly: where HAND agrees, where it differs, and
  why that difference is useful or concerning.

Result:

- Complete on `2026-05-14`.
- `tools/hand/compare_to_reference.py` compares HAND COG thresholds against
  FEMA NFHL Flood Hazard Zones where `SFHA_TF = 'T'`.
- Reports and visual panels are committed under `docs/qa/hand-reference/`.
- Birmingham 6ft result: IoU `0.379`, precision `0.536`, recall `0.563`,
  HAND coverage `6.96%`, precision lift vs same-coverage random `8.087x`.
- Houston 6ft result: IoU `0.235`, precision `0.282`, recall `0.585`,
  HAND coverage `52.07%`, precision lift vs same-coverage random `1.124x`.
- Decision: HAND is promising in relief/valley terrain and weak as a standalone
  discriminator in very flat coastal terrain. Do not treat this as national
  validation yet.
- Next validation improvement: preserve or regenerate source DEM rasters so the
  report can compare HAND against an absolute-elevation baseline.

### Gate 4: Algorithm Sensitivity

Goal: avoid scaling a fragile parameter choice.

Success criteria:

- Birmingham or Houston sensitivity run covers stream burn and accumulation
  threshold variants.
- Report includes drain-cell fraction, 3ft area percentage, and Jaccard vs the
  current configuration.
- Parameters are either frozen with a short rationale or flagged for region
  overrides before national build work.

Result:

- Complete on `2026-05-14` for Houston-first sensitivity.
- `tools/hand/run_sensitivity.py` ran 12 Houston variants:
  burn depths `0m`, `2m`, `5m`; accumulation thresholds `0.25`, `1`, `4`,
  and `16 km^2`.
- Report committed under `docs/qa/hand-sensitivity/houston-bayou-pilot/`.
- Current baseline `burn5m-acc1km2` at 6ft: coverage `52.07%`, precision
  `0.282`, recall `0.585`, precision lift `1.124x`.
- Best Houston variant `burn5m-acc16km2` at 6ft: coverage `18.54%`, precision
  `0.486`, recall `0.357`, precision lift `1.927x`, Jaccard vs baseline
  `0.331`.
- Decision: stricter accumulation improves Houston substantially, but still
  misses the `>=2.0x` flat-terrain target. Treat HAND as a terrain/drainage
  screen, not a standalone national floodplain detector.

### Gate 5: One HUC-Scale Build

Goal: prove the compute shape before CONUS.

Success criteria:

- One HUC4-scale region generates end to end on Cube.
- Report includes wall time, peak RSS, source COG bytes, valid-cell percentage,
  and 3ft area percentage.
- Go threshold: under 3 hours wall time, under 24GB peak RSS, source COG under
  500MB, and no obvious boundary artifacts inside the generated region.

Result:

- Complete on `2026-05-14` for HUC4 `0312` Ochlockonee at 10m.
- Cube run: `809.6s` wall time, `16506.0 MB` peak RSS, `193111309` byte
  source COG, `95.38%` valid cells, and `17.55%` of valid cells at or below
  3ft drainage height.
- Report committed under `docs/qa/hand-huc-scale/huc4-0312-ochlockonee/`.
- Decision: conditional pass. The current bbox-based generator can handle one
  small real HUC4 on Cube, but it does not prove boundary correctness or
  feasibility for the largest HUC4s.
- Opus review accepted the compute gate and identified cross-HUC drainage
  incoherence as the next dominant risk.

### Gate 6: Boundary-Correct Region Tiling

Goal: prove that adjacent regional outputs can mosaic without visible or
hydrologic seams.

Success criteria:

- Run a neighboring HUC4 pair with buffered DEM inputs and polygon-clipped HAND
  outputs.
- Report per-region wall time, peak RSS, source COG bytes, and clipped valid
  area.
- Compare HAND values along the shared boundary and record seam disagreement
  statistics.
- Go threshold: no obvious seam in preview imagery and boundary disagreement is
  explainable by nodata/coastline/true drainage differences, not synthetic
  bbox edges.

## Kill Or Pivot Criteria

- If external-reference overlap is very low and the disagreement is not
  explainable, pivot the pitch away from "flood map" toward "terrain/drainage
  explorer."
- If sensitivity changes swing low-ground coverage by roughly 2x without a
  principled parameter choice, stop before CONUS and redesign the algorithm.
- If one HUC-scale build exceeds Cube's practical memory/time budget, do not
  start a national run; redesign the tiling/build strategy first.
