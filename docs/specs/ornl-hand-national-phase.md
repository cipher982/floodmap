# ORNL HAND National Phase

Status: active
Owner: Codex

## Goal

Move Floodmap from a promising one-region HAND demo to a defensible national
drainage-relief product.

The product claim is:

> Show how close land is to its local drainage network, nationwide.

The product must not claim flood probability, storm forecasting, sewer capacity,
or official FEMA/regulatory status.

## Operating Rules

- Keep large source rasters, scratch files, generated COGs, and caches on Cube
  under `/mnt/storage/floodmap`; do not put them on the laptop or in git.
- Use ORNL CFIM v0.21 HUC6 archives as the current source HAND dataset.
- Keep the browser/client model slider-driven: raw HAND values are fetched once
  and recolored client-side.
- Validate against external references before scaling a region pattern.
- Commit code/docs/reports in small phases; leave generated data outside git.

## Gate 11: Birmingham Reference Validation

Why:

Birmingham is the product-risk test that exposed the original sea-level/elevation
failure. If ORNL HAND does not tell a better story there, the pivot is weak.

Tasks:

1. Retrieve ORNL CFIM v0.21 HUC6 `031601` to Cube.
2. Convert `031601hand.tif` into a uint16-decimeter COG and manifest.
3. Extract the paired ORNL elevation raster for low-elevation baseline metrics.
4. Serve the Birmingham area from the ORNL manifest on the Cube review app.
5. Run FEMA NFHL SFHA comparison at `1ft`, `3ft`, `6ft`, `10ft`, and `20ft`.
6. Run `all_touched` and strict rasterization sensitivity.
7. Write a gate decision with metrics, screenshots, and caveats.

Pass criteria:

- Cube review URL shows streets plus HAND overlay around Birmingham.
- Dynamic HAND sample and z12 tile return from the ORNL COG without code changes.
- At least one practical threshold has precision lift vs low-elevation baseline
  `>= 1.5x`.
- Visual panels show coherent creek/valley corridors, not generic elevation
  blobs or obvious processing artifacts.
- Strict rasterization does not reverse the qualitative result.

Fail criteria:

- Birmingham looks no more meaningful than absolute elevation.
- FEMA comparison is dominated by nodata or coverage holes to the point that no
  product decision is possible.
- The visual layer has discontinuities, boundary artifacts, or missing basemap
  behavior that would mislead a reviewer.

## Gate 12: Region Packaging

Why:

One HUC6 should become a repeatable package, not a hand-built exception.

Tasks:

1. Add or tighten a single command path for ORNL HUC6 ingest.
2. Produce a manifest, ingest report, validation report, and review URL for a
   given HUC6.
3. Record input bytes, output COG bytes, nodata percent, bounds, CRS, and wall
   clock conversion time.
4. Keep the command object-storage compatible even while paths are local.

Pass criteria:

- A new HUC6 can be ingested by changing only the HUC id and source archive path.
- Reports are deterministic enough to compare across regions.
- Existing unit tests and JS tests pass.
- No large generated artifacts are staged in git.

## Gate 13: National Scale Plan

Why:

National ambition is storage-feasible only if source rasters are the product of
record and web tiles are delivery/cache artifacts.

Tasks:

1. Inventory ORNL HUC6 archive availability and expected total compressed size.
2. Estimate COG output size from measured pilots.
3. Decide region granularity for manifests and runtime lookup.
4. Define the cache policy for z9-z14 tiles.
5. Identify the smallest national build that is worth showing publicly.

Pass criteria:

- The national source and delivery storage budget is bounded with measured pilot
  ratios, not raw bbox guesses alone.
- The build can run on Cube without laptop storage pressure.
- Any SageMaker use has a clear reason: faster parallel ingest or memory-heavy
  validation, not vague "more power".

## Gate 14: Product Surface

Why:

The current UI was built around sea-level/elevation. HAND needs different words
and different defaults.

Tasks:

1. Rename user-facing copy from flood level to drainage height where appropriate.
2. Pick threshold presets that match HAND interpretation.
3. Add a clear "what this is / is not" explanation outside the map surface.
4. Keep the tool-first map experience; avoid a marketing landing page.

Pass criteria:

- A PM can explain the product in one sentence without overclaiming.
- A user can inspect a city and understand that the slider means height above
  local drainage.
- The map still loads with streets, controls, legend, and shareable state.
