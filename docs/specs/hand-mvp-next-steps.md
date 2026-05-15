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

Result:

- Complete on `2026-05-14` for HUC4 pair `0106` Saco and `0107` Merrimack.
- Method: 10m DEM, 5km buffered compute extent, polygon-clipped HAND output.
- Saco run: `1232.47s`, `37530.5 MB` peak RSS, `168840015` byte COG,
  `51.6%` valid clipped cells, `14.38%` 3ft area.
- Merrimack run: `1636.2s`, `38321.0 MB` peak RSS, `201319226` byte COG,
  `45.62%` valid clipped cells, `8.68%` 3ft area.
- Seam report committed under `docs/qa/hand-boundary/pair-0106-0107-buffer5km/`.
- Boundary seam result: pass. Shared boundary length `371539.83m`; `45900`
  samples; `45867` valid paired samples; either-side <=3ft samples `0.466%`.
- Compute result: fail. Both regions cleared wall time and COG size, but peak
  RSS exceeded the 24GB budget.
- Decision: buffered polygon clipping is directionally sound for seams, but the
  current monolithic in-memory HUC build is not the CONUS builder.
- Opus review accepted Gate 6 as seam-method validation and rejected any move
  toward CONUS until Gate 7 lands. It also flagged the high-difference seam tail
  (`p95 62.97m`, max `518.7m`) as needing attribution rather than narrative
  explanation.

### Gate 7: Bounded-Memory Region Builder

Goal: make the boundary-correct method fit a predictable memory budget.

Success criteria:

- Rebuild one Gate 6 HUC4 using a tiled, chunked, or banded strategy that keeps
  peak RSS under 24GB.
- Output remains polygon-clipped and manifest-compatible as a source COG.
- Compare the bounded-memory output against the Gate 6 monolithic output for
  sampled cells and threshold masks.
- First target: Merrimack (`0107`), because it was the heavier Gate 6 region.
- Add seam-tail attribution buckets before accepting the result: coastline vs
  inland, nodata-adjacent, drain-cell-adjacent, and band-edge-adjacent samples.
- Produce a heatmap or equivalent raster QA artifact for cells where absolute
  difference from the monolithic output is greater than 1m.
- Go threshold: wall time under 3 hours, source COG under 500MB, peak RSS under
  24GB, p99 sampled HAND difference <=1m, and any larger differences are
  explainable by drain adjacency, nodata/coastline effects, or band edges rather
  than arbitrary interior seams.

Result:

- Complete on `2026-05-14` for HUC4 `0107` Merrimack using a horizontal
  banded pyflwdir builder.
- Method: 10m DEM, 5km buffered HUC output, 20km band overlap, 2000-row
  interior bands, polygon-clipped COG output.
- Compute result: pass but tight. Cube run took `9222.96s`, peaked at
  `23698.8 MB` RSS, and wrote a `200.8 MB` COG.
- Diff result: fail. Against the Gate 6 monolithic Merrimack COG, sampled
  absolute HAND differences were p50 `0.2m`, p95 `3.7m`, p99 `20.4m`, with
  only `79.821%` of samples within `1m`.
- Threshold result: fail for product equivalence. The 3ft threshold mask
  Jaccard was `0.8405`.
- Attribution result: fail. Of `32709247` cells with >1m difference,
  `94.256%` were unattributed interior cells, not explained by band edges,
  nodata adjacency, drain adjacency, or HUC-boundary/coastline proxy effects.
- Report committed under
  `docs/qa/hand-banded/huc4-0107-merrimack-buffer5km-clipped-banded-overlap20km-rows2000/`.
- Decision: horizontal bands solve peak RAM but do not preserve hydrologic
  correctness well enough. Do not scale this algorithm to CONUS.

### Gate 8: Hydrologic Work Unit Benchmark

Goal: pick the production decomposition and HAND engine before starting CONUS
batching.

Success criteria:

- First test whether smaller hydrologic units solve the problem: run a
  monolithic pyflwdir HUC8/HUC10 unit inside Merrimack with 5km buffer and
  polygon-clipped output.
- Use hydrologic work units with explicit buffer handling, not arbitrary
  horizontal DEM bands.
- If the HUC8/HUC10 pyflwdir path does not pass, run a comparable benchmark
  through at least one native hydrology engine candidate: GRASS, WhiteboxTools,
  or TauDEM.
- Report wall time, peak RSS, output size, selected drainage cells, valid area,
  3ft/6ft/10ft threshold coverage, and failure modes.
- Compare each candidate against the Gate 6 monolithic pyflwdir HUC4 output and
  the failed Gate 7 banded output where extents overlap.
- Produce automated diff and visual artifacts for >1m differences and threshold
  masks.
- Go threshold for a production path: p99 sampled HAND difference <=1m versus
  the Gate 6 HUC4 reference where comparable, >=99% of paired cells within 1m,
  threshold-mask Jaccard >=0.97 at 3ft/6ft/10ft, no obvious interior artifacts,
  and a credible path to process-level parallelism by HUC8/HUC10.
- Decision rule: prefer the simplest decomposition and engine that preserves
  hydrologic correctness. If HUC8/HUC10 monolithic pyflwdir passes, avoid
  native-engine churn until a larger-region benchmark proves it is needed.

First result:

- HUC8 `01070006` Merrimack River monolithic pyflwdir completed on Cube in
  `637.51s`, peaked at `18209.4 MB` RSS, and wrote a `72.3 MB` COG.
- Compute result: pass. Smaller hydrologic units fit the memory and wall-clock
  budget much better than HUC4 bands or HUC4 monolithic runs.
- Correctness result: fail against the HUC4 `0107` monolithic reference where
  extents overlap. Sampled p50/p95/p99 differences were `0.2m`, `2.4m`,
  `10.7m`; only `85.19%` of samples were within `1m`.
- Threshold-mask result: fail. 3ft/6ft/10ft Jaccard was
  `0.5785` / `0.5976` / `0.6204`.
- Report committed under
  `docs/qa/hand-unit/huc8-01070006-merrimack-river-buffer5km-clipped/`.
- Decision: HUC8 monolithic pyflwdir improves resource use but does not match
  the larger HUC4 reference well enough on this downstream Merrimack unit. The
  next benchmark should test whether a native engine or explicit
  cross-boundary drainage handling fixes the lost upstream/downstream context.

Second result:

- HUC8 `01070006` Merrimack River through WhiteboxTools
  `ElevationAboveStream` completed on Cube in `167.06s`, peaked at
  `18209.3 MB` RSS, and wrote an `11.2 MB` COG.
- Compute result: pass. Whitebox itself runs quickly enough for this unit.
- Coverage result: fail for a production path. Only `3.43%` of the polygon
  footprint had valid output. Whitebox warned that the raw DEM contains interior
  pit cells and likely needs depression/flat conditioning before this tool.
- Correctness result: fail against the Gate 6 HUC4 pyflwdir reference where
  extents overlap. Sampled p50/p95/p99 differences were `0.3m`, `3.5m`,
  `9.229m`; only `78.337%` of samples were within `1m`.
- Threshold-mask result: fail. 3ft/6ft/10ft Jaccard was
  `0.1386` / `0.1346` / `0.1278`.
- Report committed under
  `docs/qa/hand-whitebox/huc8-01070006-merrimack-river-buffer5km-clipped-whitebox-eas/`.
- Decision: this Whitebox configuration is a useful smoke rejector, not a
  production candidate. It uses a different drain definition from the pyflwdir
  reference: rasterized mapped streams on a raw DEM, without the accumulation
  drain mask used by the current reference. Do not start CONUS batching from
  this result.
- Next benchmark: isolate the likely root cause by keeping pyflwdir, keeping
  the HUC8 output unit, and computing with larger upstream/parent hydrologic
  context before clipping back to the HUC8 polygon.

Third result:

- HUC8 `01070006` output computed with parent HUC6 `010700` context completed
  on Cube in `1435.86s`, peaked at `38325.7 MB` RSS, and wrote a `70.1 MB`
  COG.
- Compute result: fail for the production budget. The run finished under the
  wall-clock target, but parent-context monolithic pyflwdir exceeded the
  `24 GB` peak RSS target.
- Correctness result: fail against the Gate 6 HUC4 pyflwdir reference where
  extents overlap. Sampled p50/p95/p99 differences were `0.3m`, `2.8m`,
  `16.2m`; only `80.875%` of samples were within `1m`.
- Threshold-mask result: fail. 3ft/6ft/10ft Jaccard was
  `0.5547` / `0.5784` / `0.6044`.
- Report written under
  `docs/qa/hand-context/huc8-01070006-merrimack-river-context-huc6-010700-buffer5km-clipped/`.
- Decision: naive parent-context compute does not rescue the HUC8 work-unit
  result, and it loses the memory advantage that made HUC8 attractive. The
  likely issue is not just missing immediate parent context; it is that
  region-local pyflwdir outputs are not equivalent enough to the larger
  reference without a more principled hydrologic production method.

Gate verdict:

- Gate 8 fails. No tested bounded-memory or smaller-work-unit path preserves
  enough hydrologic correctness to justify CONUS batching from the current
  algorithm family.
- Product implication: pause national "flood map" execution. The defensible
  near-term product is a terrain/drainage explorer or curated regional HAND
  viewer, not a nationwide flood-risk model.

### Gate 9: Precomputed National HAND Ingest

Goal: test whether an external precomputed HAND product can replace our
self-built national HAND compute path.

Success criteria:

- Download one real external HUC6 HAND package directly to Cube.
- Convert its source HAND raster to the app's `uint16` decimeter COG format.
- Generate a terrain manifest that can be served by the existing terrain-v2 API.
- Render sample app tiles and point samples from the converted COG.
- Compare the converted product against the prior Gate 6 Merrimack reference,
  but do not treat the self-built reference as ground truth.

Result:

- Complete on `2026-05-15` for ORNL CFIM v0.21 HUC6 `010700`.
- Source archive on Cube:
  `/mnt/storage/floodmap/data/hand-precomputed/ornl-cfim-v0.21/010700/010700.zip`
  (`8,222,025,235` bytes).
- Extracted source HAND raster: `14,427 x 21,615`, `float32`, `EPSG:4269`,
  LZW-compressed scanline GeoTIFF, no overviews.
- Converted app COG:
  `/mnt/storage/floodmap/data/terrain/hand-precomputed/ornl-cfim-v0.21/010700/010700hand-u16dm.cog.tif`
  (`172,578,583` bytes), tiled `512 x 512`, `uint16`, nodata `65535`,
  overviews `[2, 4, 8, 16, 32, 64]`.
- Conversion took `51.054s` on Cube and wrote a one-region manifest at
  `/mnt/storage/floodmap/data/terrain/manifests/ornl-cfim-v0p21-010700.json`.
- Tile smoke passed through the app's dynamic COG renderer for z10/z12/z14
  tiles around Manchester, Nashua, Concord, Lowell, and Haverhill.
- Distribution: `167,329,470` valid cells (`53.659%`), p50 HAND `22.2m`,
  p95 `161.8m`, p99 `342.0m`.
- Low-HAND coverage: `8.755%` of valid cells at or below 3ft, `11.623%` at or
  below 6ft, and `15.089%` at or below 10ft.
- Against the Gate 6 HUC4 Merrimack pyflwdir reference, sampled absolute
  differences were p50 `1.7m`, p95 `64.205m`, p99 `176.766m`, with `40.576%`
  within 1m. Threshold-mask Jaccard was `0.5739` / `0.5997` / `0.6314` at
  3ft/6ft/10ft.
- Report committed under
  `docs/qa/hand-precomputed/ornl-cfim-v0p21-huc6-010700/`.

Decision:

- Ingest/render path: pass. External precomputed HAND can be transformed into
  the existing Floodmap serving format quickly and compactly.
- Product correctness: unresolved. ORNL CFIM and our self-built pyflwdir
  reference differ materially, so the next gate should compare ORNL against an
  external floodplain/drainage reference and visual corridor expectations, not
  against our failed prototype as if it were truth.
- Strategic implication: prefer external precomputed HAND products over a
  self-built CONUS hydrology engine unless a later gate proves the external data
  is unavailable or unsuitable at national coverage.

## Kill Or Pivot Criteria

Current state: triggered.

- If external-reference overlap is very low and the disagreement is not
  explainable, pivot the pitch away from "flood map" toward "terrain/drainage
  explorer."
- If sensitivity changes swing low-ground coverage by roughly 2x without a
  principled parameter choice, stop before CONUS and redesign the algorithm.
- If one HUC-scale build exceeds Cube's practical memory/time budget, do not
  start a national run; redesign the tiling/build strategy first.
