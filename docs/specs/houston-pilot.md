# Houston HAND Pilot

Status: Opus reviewed; implementation plan fixed
Owner: Codex

## Goal

Add one second geography to the Cube MVP so the product is no longer a
single-city demo. Houston is intentionally different from Birmingham: flatter,
bayou-driven, Gulf Coast terrain where a drainage-relative slider should tell a
different story than a hilly inland creek corridor.

## Region

- Region id: `houston-bayou-pilot`
- Title: `Houston Bayou HAND Pilot`
- Bbox: `[-95.82, 29.45, -94.95, 30.15]`
- Source COG: `/mnt/storage/floodmap/data/terrain/hand/houston-bayou-pilot.tif`
- Cube manifest: `/mnt/storage/floodmap/data/terrain/manifest.json`
- Dataset version for Cube review: `hand-houston-20260514a`
- Downtown sample: `lat=29.7604`, `lng=-95.3698`
- Bayou review center: `lat=29.7130`, `lng=-95.4120`, `zoom=11`, `view=hand`,
  `water=2.0`

## Non-Goals

- Do not start full CONUS.
- Do not tune the algorithm to make Houston pretty.
- Do not claim rainfall, storm sewer, FEMA, or forecast behavior.
- Do not use generative AI to sharpen or invent terrain-risk pixels.

## Phase 0: Plan Review

Status: complete (`2026-05-14`)

Tasks:

- Write this pilot plan.
- Ask Hatch Opus to review before implementation.

Success criteria:

- Opus verdict is `GO` or blocking findings are fixed.
- Memory, tile-content, drainage-name, drain-fraction, Birmingham-regression,
  manifest-routing, and rollback criteria are explicit in this file.

Result:

- Initial Hatch Opus review: `GO WITH FIXES`.
- Final focused Hatch Opus review after criteria fixes: `GO`.

## Phase 1: Configurable Region Generator

Status: complete (`2026-05-14`)

Tasks:

- Extract the Birmingham generator logic into a reusable region generator.
- Keep the existing Birmingham entry point working.
- Add a CLI that accepts region parameters rather than hardcoding globals.
- Preserve `FLOODMAP_DATA_ROOT` support for source COG output.

Success criteria:

- Birmingham validation still passes locally.
- Unit/static checks pass for the new generator code.
- The old Birmingham script remains a thin compatibility wrapper or still works.
- The new CLI can regenerate Birmingham into a scratch output directory and
  compare back to the current source COG/static tiles within the existing
  tolerance.

Result:

- Added generic CLI: `tools/hand/generate_region_hand.py`.
- Kept `tools/prototypes/generate_birmingham_drainage.py` as the underlying
  default-Birmingham entry point.
- Local Birmingham dynamic validation still passes against the existing COG and
  prototype tiles.
- Focused local checks passed: `uvx ruff check`, `uvx ruff format --check`, and
  `uv run pytest tests/unit/test_config.py -q`.

## Phase 2: Houston Cube Build

Status: complete (`2026-05-14`)

Tasks:

- Run the Houston generator on Cube, using `/mnt/storage/floodmap/data`.
- Write source COG, metadata, QA report, and preview.
- Static web tiles are QA-only if produced; serving must use the source COG.
- Record DEM size, selected flowline count, drain cells, COG size, and tile
  counts.
- Record peak RSS and wall time for the build.

Success criteria:

- Houston source COG exists and is non-empty.
- Metadata and QA report exist.
- Peak RSS is recorded and under `8 GiB`. If the build exceeds that cap, stop
  and review memory behavior before serving Houston.
- Wall time is recorded and under `30 minutes`. If the build exceeds that cap,
  stop and review before serving Houston.
- Selected drainage flowlines include named bayous or creeks from the Houston
  bbox. At least one of Buffalo Bayou, Brays Bayou, White Oak Bayou, Sims
  Bayou, Greens Bayou, or Cypress Creek must appear in the named sample, or
  the run stops for drainage-selection review.
- At least one valid HAND cell exists.
- Drain-cell fraction of valid DEM cells is recorded and below `20%`, or the
  run is stopped for algorithm review before serving.
- The `3 ft` threshold area is recorded and below `60%` of valid HAND cells, or
  the run is stopped for algorithm review before serving.
- Cube storage paths resolve outside `/mnt/gemini`.

Result:

- Cube source COG:
  `/mnt/storage/floodmap/data/terrain/hand/houston-bayou-pilot.tif`.
- Source COG size: `46M` (`48,170,590` bytes).
- DEM grid: `8911 x 8240`.
- Selected flowlines: `3,083` of `6,100`.
- Named sample includes `Buffalo Bayou`, `Greens Bayou`, `Cypress Creek`,
  `Brays Bayou`, and `Sims Bayou`.
- Valid HAND cells: `69,704,089`.
- Drain-cell fraction: `1.038%`.
- `3 ft` threshold area: `30.69%`.
- Peak RSS: `4,477.9 MB`.
- Wall time: `210.5 seconds`.
- Cube path guard passed outside `/mnt/gemini`.

## Phase 3: Multi-Region Serving

Status: complete (`2026-05-14`)

Tasks:

- Build a Cube terrain manifest containing Birmingham and Houston.
- Restart the Cube API with `TERRAIN_MANIFEST_PATH` pointing at that manifest.
- Keep the existing Cube Tailscale-only ports.

Success criteria:

- Birmingham sample still returns non-null HAND.
- Houston sample returns non-null HAND.
- A Houston review tile returns `131072` bytes after decompression
  (`256 x 256 x uint16`) and has at least `10%` non-NODATA pixels.
- Vector basemap endpoint returns `200` or `204` for the Houston review tile.
- API probes show Birmingham coordinates resolve to the Birmingham region and
  Houston coordinates resolve to the Houston region.
- Browser review URL renders street basemap plus Drainage overlay in Houston.
- Before swapping `/mnt/storage/floodmap/data/terrain/manifest.json`, copy it to
  `/mnt/storage/floodmap/data/terrain/manifest.pre-houston.json`.
- If any Phase 3 success criterion fails, restore the backup with:
  `cp /mnt/storage/floodmap/data/terrain/manifest.pre-houston.json /mnt/storage/floodmap/data/terrain/manifest.json`
  and restart the Cube API before sharing any review URL.

Result:

- Wrote rollback manifest:
  `/mnt/storage/floodmap/data/terrain/manifest.pre-houston.json`.
- Wrote active two-region manifest:
  `/mnt/storage/floodmap/data/terrain/manifest.json`.
- Restarted Cube API with `TERRAIN_MANIFEST_PATH` set.
- Metadata returns dataset `hand-houston-20260514a` with `2` regions.
- Birmingham sample returns `8.2m` / `26.9ft`, region
  `birmingham-prototype`.
- Houston review sample returns `1.4m` / `4.6ft`, region
  `houston-bayou-pilot`.
- Houston vector tile z11 `481/846` returned `200`.
- Houston HAND tile z11 `481/846` returned `131072` decompressed bytes,
  `96.37%` non-NODATA pixels, and `x-terrain-source: dynamic-cog`.
- Browser QA loaded `hand` mode with one MapLibre canvas and no blocking
  console or page errors.
- Screenshot showed Houston streets plus the Drainage overlay. Visual result is
  much broader than Birmingham, consistent with the flat-terrain caveat.

## Phase 4: Review Gate

Status: complete (`2026-05-14`)

Tasks:

- Run browser/API QA from the laptop.
- Ask Hatch Opus to review results before handoff.

Success criteria:

- Opus verdict is `GO`.
- The final handoff includes the Houston review URL and the known limitations:
  no storm sewer model, no pluvial rainfall model, no FEMA/return-period model,
  no subsidence model, no tidal surge model, and flat-terrain HAND can
  over-widen low corridors.

Result:

- Final Hatch Opus review verdict: `GO`.
- No blockers remain for user review.
