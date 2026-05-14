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

## Phase 2: Data Bootstrap

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

## Phase 3: End-to-End Cube Runtime

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

## Phase 4: Laptop Review URL

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

## Phase 5: Pilot Region Readiness

Tasks:

- Confirm the existing Birmingham generation script can run from Cube.
- Add a second-region runner only after Cube runtime works.
- Capture per-run metrics: input bytes, COG bytes, tile latency, nodata percent,
  and sample screenshots.

Success criteria:

- Birmingham can be regenerated or validated on Cube.
- The same runtime can serve generated data without code changes.
- Any second-region work gets its own follow-up plan and review gate.

## Out Of Scope For This MVP

- Full CONUS data build.
- Public deployment.
- GPU acceleration.
- Rainfall, storm sewer, FEMA, or forecast modeling.
- National z14/z15 precompute.
