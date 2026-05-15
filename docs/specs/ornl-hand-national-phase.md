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

## Gate 11: Region Packaging

Why:

One HUC6 should become a repeatable package, not a hand-built exception.

Tasks:

1. Ingest a HUC6 with the single command path:
   `uv run python tools/hand/ingest_ornl_huc6.py --huc <HUC6>`.
2. Produce a manifest, ingest report, validation report, and review URL for a
   given HUC6.
3. Record input bytes, source ZIP SHA-256, output COG bytes, nodata percent,
   bounds, CRS, and wall clock conversion time.
4. Keep the command object-storage compatible even while paths are local.
5. Do not include Globus, FEMA validation, or review-app startup inside the
   ingest command; those are separate workflow steps.

Pass criteria:

- A new ORNL HUC6 archive on disk can be ingested by changing only the HUC id
  and optional archive path.
- The ingest command supports a no-write dry run for checking a new archive.
- Reports are deterministic enough to compare across regions.
- Existing unit tests and JS tests pass.
- No large generated artifacts are staged in git.

## Gate 12: Birmingham Reference Validation

Why:

Birmingham is the product-risk test that exposed the original sea-level/elevation
failure. If ORNL HAND does not tell a better story there, the pivot is weak.

Blocked:

- ORNL CFIM v0.21 HUC6 `031601` currently requires interactive Globus auth.
  The required user task is in the docket:
  `no-date--transfer-ornl-cfim-huc6-031601-zip-to-cube.md`.

Tasks:

1. Retrieve ORNL CFIM v0.21 HUC6 `031601` to Cube.
2. Convert `031601hand.tif` into a uint16-decimeter COG and manifest.
3. Extract the paired ORNL elevation raster for low-elevation baseline metrics.
4. Serve the Birmingham area from the ORNL manifest on the Cube review app.
5. Run FEMA NFHL SFHA comparison with
   `uv run python tools/hand/run_reference_gate.py ...`.
6. Confirm the generated `all_touched` and strict rasterization sensitivity.
7. Write a gate decision with metrics, screenshots, and caveats.

Pass criteria:

- Cube review URL shows streets plus HAND overlay around Birmingham.
- Dynamic HAND sample and z12 tile return from the ORNL COG without code changes.
- The low-elevation baseline is the paired ORNL elevation raster extracted from
  the same HUC6 archive.
- At least one practical threshold has precision lift vs low-elevation baseline
  `>= 1.5x`.
- FEMA-in-HAND-nodata is reported; if it exceeds `60%`, the gate can only pass
  with a written caveat explaining why the remaining overlap is still useful.
- Visual panels show coherent creek/valley corridors, not generic elevation
  blobs or obvious processing artifacts.
- Strict rasterization does not reverse the qualitative result.

Fail criteria:

- Birmingham looks no more meaningful than absolute elevation.
- FEMA comparison is dominated by nodata or coverage holes to the point that no
  product decision is possible.
- The visual layer has discontinuities, boundary artifacts, or missing basemap
  behavior that would mislead a reviewer.

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
- The first national source-raster budget is `<= 2 TB` on Cube. If measured
  pilots extrapolate above that, stop and redesign before downloading all CONUS.
- The first delivery/cache budget is `<= 500 GB` for the serious demo tier.
- The build can run on Cube without laptop storage pressure.
- SageMaker is only used for a named reason: faster parallel ingest or
  memory-heavy validation, not vague "more power".

## Gate 14: Product Surface

Why:

The current UI was built around sea-level/elevation. HAND needs different words
and different defaults.

Tasks:

1. Rename user-facing copy from flood level to drainage height where appropriate.
2. Pick threshold presets that match HAND interpretation.
3. Add a clear "what this is / is not" explanation outside the map surface.
4. Keep the tool-first map experience; avoid a marketing landing page.
5. Audit the UI for claims that imply flood probability, official FEMA status,
   insurance risk, forecasts, storm sewer capacity, or time-to-flood.

Pass criteria:

- A PM can explain the product in one sentence without overclaiming.
- A user can inspect a city and understand that the slider means height above
  local drainage.
- The map still loads with streets, controls, legend, and shareable state.
- Screenshot QA confirms the legend, slider, and mode labels use HAND language.
