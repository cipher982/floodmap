# Cube MVP Epic

Status: Opus reviewed; implementation plan fixed for Cube
Owner: Codex

## Goal

Run Floodmap end-to-end on Cube as the build/review environment for the HAND
refactor. The laptop should stay a control surface, not the place where national
data or large caches accumulate.

## Principles

- Use Cube for CPU, disk, and long-running data jobs.
- Do not use `/mnt/gemini`; it is quarantined/unreliable.
- Do not add GPU workloads; Floodmap HAND work is CPU/storage/network bound.
- Keep source data, scratch data, generated COGs, and terrain caches out of git.
- Commit code/docs in small phases before larger data work.
- Bind review services to Cube's Tailscale IP only: `100.125.140.78`.

## Cube Decisions

- Workspace root: `/mnt/storage/floodmap`.
- Repo checkout: `/mnt/storage/floodmap/repo`.
- Runtime data root: `/mnt/storage/floodmap/data`.
- Scratch root: `/mnt/storage/floodmap/scratch`.
- API review port: `18000`.
- Tileserver review port: `18080`.
- Terrain cache cap: `21474836480` bytes (`20 GiB`) for the MVP.
- Runtime shape: run `tileserver-gl` in Docker and FastAPI via `uv run` from the
  Cube repo checkout. This MVP deliberately avoids the production compose stack
  and Coolify network.

## Phase 0: Plan Review

Tasks:

- Write this epic with concrete success criteria.
- Ask Hatch Opus to review the plan before implementation.
- Address preflight blockers before provisioning anything persistent on Cube.

Success criteria:

- Opus verdict is `GO` or all blocking findings are fixed.
- Cube storage root, ports, runtime shape, and cache cap are explicit in this
  file.
- Root repo working tree is clean after the planning commit.

## Phase 1: Cube Workspace

Status: complete (`2026-05-14`)

Tasks:

- Verify live Cube storage, mounts, OS, Docker, Tailscale address, and port
  availability.
- Create the dedicated Floodmap workspace under `/mnt/storage/floodmap`, not
  `/mnt/gemini`.
- Sync or clone the repo at the current commit.
- Create data directories for basemaps, terrain source rasters, terrain cache,
  and scratch files.
- Add a guard command that resolves all configured Cube paths with
  `readlink -f` and fails if any path lands under `/mnt/gemini`.

Success criteria:

- `ssh cube` works.
- `df -h /mnt/storage` shows enough free space for the MVP.
- Configured paths resolve under `/mnt/storage/floodmap`.
- The repo on Cube reports the same commit as local.
- No files are written under `/mnt/gemini`.
- Ports `18000` and `18080` are free before startup.

Result:

- Cube Tailscale IP: `100.125.140.78`.
- `/mnt/storage`: `7.3T` total, `3.3T` available.
- `/mnt/gemini` is mounted live but intentionally unused.
- Workspace root: `/mnt/storage/floodmap`.
- Cube repo commit: `dad80fd865bc6d4c859c512a2bac376004d9a02e`.
- `/home/drose/.local/bin/uv` is available on Cube.
- Ports `18000` and `18080` were free before startup.

## Phase 2: Data Bootstrap

Status: complete (`2026-05-14`)

Tasks:

- Rsync the existing local basemap to Cube:
  `data/base-maps/usa-complete.mbtiles`.
- Rsync the existing local Birmingham HAND COG to Cube:
  `data/terrain/hand/birmingham-drainage.tif`.
- Keep original elevation source/tile datasets optional for this MVP.
- Set `TERRAIN_CACHE_MAX_BYTES=21474836480`.

Success criteria:

- Cube has `usa-complete.mbtiles` and `birmingham-drainage.tif`.
- Data paths match the app's expected mount/env layout.
- `du -sh` output is captured for each dataset directory.
- Terrain cache cap is explicit, not default-unbounded.
- If the local HAND COG is missing, stop and regenerate it on Cube before
  continuing.

Result:

- Cube repo commit: `136c67af00da0a308985c8e9b16c30c9c4e4df96`.
- `data/base-maps`: `1.7G`.
- `data/terrain/hand`: `40M`.
- `data/terrain/tile-cache`: empty before runtime.
- `FLOODMAP_DATA_ROOT=/mnt/storage/floodmap/data` resolves the basemap and
  Birmingham HAND COG from the Cube API process.

## Phase 3: End-to-End Cube Runtime

Status: complete (`2026-05-14`)

Tasks:

- Start `tileserver-gl` against the Cube basemap on
  `100.125.140.78:18080`.
- Start FastAPI with `TERRAIN_V2_ENABLED=true`.
- Point FastAPI at `http://100.125.140.78:18080`.
- Bind FastAPI to `100.125.140.78:18000`.
- Do not open public internet access.

Success criteria:

- `GET /api/health` returns a JSON response.
- Vector tile endpoint returns `200` or `204`, not `503`.
- HAND metadata endpoint returns the Birmingham dataset version.
- HAND sample for downtown Birmingham returns a non-null height.
- A HAND `.u16` tile returns `131072` bytes after decompression.
- The app page loads with `view=hand` and the basemap configured.

Result:

- `tileserver-gl` container: `floodmap-cube-tileserver`.
- Tileserver URL: `http://100.125.140.78:18080`.
- FastAPI URL: `http://100.125.140.78:18000`.
- Runtime env uses `FLOODMAP_DATA_ROOT=/mnt/storage/floodmap/data`,
  `TERRAIN_V2_ENABLED=true`, `TERRAIN_CACHE_MAX_BYTES=21474836480`, and
  `TILESERVER_URL=http://100.125.140.78:18080`.
- `/api/health` returns JSON. Status is `critical` because original elevation
  source tiles are intentionally absent from this MVP.
- Vector endpoint returned `200` for Birmingham z12.
- HAND metadata returned `hand-birmingham-20260513a`.
- Downtown Birmingham sample returned `8.2m` / `26.9ft` from `source-cog`.
- HAND z12 tile returned `131072` decompressed bytes with
  `x-terrain-source: dynamic-cog`.
- API needed `uv run --with rasterio --with affine` for dynamic COG serving.

## Phase 4: Laptop Review URL

Status: complete (`2026-05-14`)

Tasks:

- Bind the review service to Cube's Tailscale interface only.
- Confirm the URL is reachable from the laptop.
- Keep exposure Tailscale-only unless explicitly deploying publicly.

Success criteria:

- Laptop can load the Cube-hosted app URL.
- Basemap streets and HAND overlay both render.
- Browser console has no blocking tile or worker errors.
- The review URL is documented in the final handoff.
- Prod `https://drose.io/floodmap` is unaffected by the Cube MVP.

Result:

- Review URL:
  `http://100.125.140.78:18000/?lat=33.5186&lng=-86.8104&zoom=12&view=hand&water=2.0`
- Browser QA loaded `window.floodMap` in `hand` mode with one MapLibre canvas.
- Screenshot showed vector streets plus the HAND Drainage overlay.
- Console/page-error check found no blocking tile or worker failures. The only
  console error was a non-blocking COOP warning caused by plain HTTP on a
  non-localhost Tailscale origin.
- Hatch Opus Phase 3/4 review verdict: `GO`.

## Phase 5: Pilot Region Readiness

Status: complete (`2026-05-14`)

Tasks:

- Confirm the existing Birmingham generation script can run from Cube.
- Add a second-region runner only after Cube runtime works.
- Capture per-run metrics: input bytes, COG bytes, tile latency, nodata percent,
  and sample screenshots.

Success criteria:

- Birmingham can be regenerated or validated on Cube.
- The same runtime can serve generated data without code changes.
- Any second-region work gets its own follow-up plan and review gate.

Result:

- `tools/hand/validate_birmingham_dynamic.py` now respects
  `FLOODMAP_DATA_ROOT`.
- Cube validation read source COG from
  `/mnt/storage/floodmap/data/terrain/hand/birmingham-drainage.tif`.
- Compared all `73` Birmingham prototype tiles.
- Valid comparison pixels: `3,499,040`.
- Absolute difference p50/p95/max: `0.00 / 0.00 / 0.00 ft`.
- NODATA mismatch: `994` pixels (`0.0208%`).
- Cube cold render p50/p95: `38.0 / 93.1 ms`.
- Cube hot render p50/p95: `0.0 / 0.0 ms`.
- Downtown sample static/dynamic: `24.3 / 25.3 ft`.
- Hatch Opus Phase 5 review verdict: `GO`.

## Out Of Scope For This MVP

- Full CONUS data build.
- Public deployment.
- GPU acceleration.
- Rainfall, storm sewer, FEMA, or forecast modeling.
- National z14/z15 precompute.

## Post-MVP Gate: Reproducible Review Runtime

Status: complete (`2026-05-14`)

Context:

- A manual API restart once omitted `TILESERVER_URL`, causing the app's vector
  proxy to return `404` from Cube's local nginx instead of tileserver-gl. HAND
  still rendered, but the street basemap disappeared.
- Hatch Opus ranked runtime reproducibility as the first gate before basemap
  polish, reference comparison, sensitivity analysis, or CONUS scale-out.

Tasks:

- Add a checked-in Cube startup script that starts tileserver-gl and FastAPI
  with the full review env.
- Add a `make cube-review` target that runs the script on Cube.
- Keep all runtime data under `/mnt/storage/floodmap/data`, never
  `/mnt/gemini`.

Success criteria:

- `scripts/cube-review-up.sh` starts the Cube review stack from the repo
  checkout.
- Vector tile proxy returns `200` for a known Birmingham tile.
- HAND metadata, sample, and tile endpoints return `200`.
- Browser smoke in `hand` mode sees rendered road features and the HAND overlay.

Result:

- `make cube-review` runs `scripts/cube-review-up.sh` on Cube.
- Script restarted `floodmap-cube-tileserver` and FastAPI with:
  - `FLOODMAP_DATA_ROOT=/mnt/storage/floodmap/data`
  - `TERRAIN_MANIFEST_PATH=/mnt/storage/floodmap/data/terrain/manifest.json`
  - `TERRAIN_V2_ENABLED=true`
  - `TILESERVER_URL=http://100.125.140.78:18080`
  - `TERRAIN_CACHE_MAX_BYTES=21474836480`
- Script smoke checks passed:
  - Vector z10 tile: `200`
  - HAND metadata: `200`
  - HAND sample: `200`
  - HAND z11 Birmingham tile: `200`
- Browser smoke loaded the Cube review URL in `hand` mode and saw `128`
  rendered road features plus `10` rendered waterway features.
