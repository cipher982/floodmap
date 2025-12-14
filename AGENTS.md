# Floodmap (drose.io/floodmap) — Agent Notes

This repo powers `https://drose.io/floodmap`: MapLibre map with client-side rendered elevation tiles + a “storm surge / sea level” slider.

## Non‑Negotiables
- Never create/overwrite `.env` (ask before appending).
- Prefer project tooling: use `uv run ...` (not `python` directly; `python` may not exist).
- Avoid long-running production commands that can hang (do **not** use `docker wait`).

## Quick Commands (Local)
- Unit tests (fast): `uv run pytest tests/unit -q`
- JS unit test: `node --test src/web/js/render-worker.test.mjs`
- Git hooks: commits run `pre-commit` (ruff/format, etc.)

## High-Level Architecture
- Frontend:
  - `src/web/js/map-client.js`: MapLibre setup, protocol handler, worker wiring, water vector mask.
  - `src/web/js/elevation-renderer.js`: client tile fetch (`.u16`), decoding, main-thread fallback rendering, cache-busting `v=...`.
  - `src/web/js/render-worker.js`: worker LUT rendering + optional OffscreenCanvas PNG encoding.
- API:
  - `src/api/routers/tiles_v1.py`: serves elevation `.u16` (precompressed/runtime), vector tiles, cache headers.
  - `src/api/routers/risk.py`: samples z11 elevation at clicked pixel; supports `isWater` hint.
  - `src/api/elevation_loader.py`: mosaics 1° DEM sources into web-mercator tiles; normalizes `-32767`→NoData and returns `None` on all-NoData mosaics.

## Production (Coolify on `clifford`)
- Health check: `curl -s https://drose.io/floodmap/api/health | head`
- SSH: `ssh clifford`
- Containers: find names via **unfiltered** `docker ps` (Coolify names change).
  - Typical: `floodmap-webapp-*` and `floodmap-tileserver-*`
- Useful:
  - Logs: `docker logs --tail 200 -f <container>`
  - Shell/Python: `docker exec -it <container> sh`
  - Mounts: `docker inspect <container> --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{\"\\n\"}}{{end}}'`
- Data mounts (host → container):
  - `/mnt/backup/floodmap/data/elevation-source` → `/app/data/elevation-source`
  - `/mnt/backup/floodmap/data/elevation-tiles` → `/app/data/elevation-tiles`
  - `/mnt/backup/floodmap/data/base-maps` → `/app/data/base-maps`

## Common Issue: “Huge blue/blank polygon” (No elevation)
Typical root cause is **corrupted/missing DEM source tile** or **cached precompressed all-NoData**.

Fast diagnosis:
- UI debug shows a tile like `z/x/y` and endpoint `/api/v1/tiles/elevation-data/z/x/y.u16`.
- Check the tile payload size:
  - `content-length: 23` (brotli) is usually an all‑NODATA tile.
  - `curl -I 'https://drose.io/floodmap/api/v1/tiles/elevation-data/11/573/819.u16?method=precompressed&v=XYZ' -H 'Accept-Encoding: br'`
- Identify the 1° source file(s) backing a tile inside the webapp container:
  - `docker exec -i <webapp> /app/.venv/bin/python - <<'PY' ... elevation_loader.num2deg/find_elevation_files_for_tile ... PY`

Repair workflow (summary):
- Replace the bad 1° source from Skadi (example URL pattern):
  - `https://s3.amazonaws.com/elevation-tiles-prod/skadi/N33/N33W080.hgt.gz`
- Regenerate the affected precompressed tiles in `/app/data/elevation-tiles`.
- Bump cache-busting `v=` (see below) so clients/Cloudflare don’t stay pinned to old immutable tiles.
- If needed, restart webapp container to flush in-process DEM caches.

Details live in `docs/` (see `docs/AGENTS.md`).

## Cache-Busting Rules of Thumb
- Elevation tile fetch includes a stable `v=` query param to avoid getting pinned to stale immutable cached tiles after repairs.
- When you change any frontend JS or need to bust tile caches, bump versions in:
  - `src/web/index.html` (script/style `?v=...`)
  - `src/web/js/elevation-renderer.js` (`qs.set('v', '...')`)
  - `src/web/js/map-client.js` (worker URL `render-worker.js?v=...`)

## Zoom / Coverage Quirk
- Client max zoom is capped to **11** to match precompressed tile coverage; do not raise unless you generate a deeper precompressed pyramid.
