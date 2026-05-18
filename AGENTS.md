# Floodmap (drose.io/floodmap) - Agent Quickstart

FastAPI serves the public app and tile APIs for `https://drose.io/floodmap`.
The browser owns MapLibre rendering: it fetches vector tiles plus raw terrain
tiles (elevation/HAND) and colors them client-side.

## Non-Negotiables
- Never create/overwrite `.env` (ask before appending).
- Prefer project tooling: `uv run ...` (do not assume `python` exists).
- Avoid `docker wait` (can hang).
- "Shipped" means live in production. Do not describe local-only commits or unpushed changes as shipped; if it is not deployed, say so plainly.
- Any user-visible JS/CSS/worker change, or global tile-cache reset, must bump `ASSET_VERSION` in `src/api/page_renderer.py` before shipping. `src/web/index.html` contains the placeholder, not the source of truth.
- Preserve the custom Umami events in `src/web/js/map-client.js` (`location_click`, `viewport_view`) when touching analytics or map event code.
- Terrain 3D uses a map camera, not a free model-viewer orbit: do not reintroduce unbounded yaw, pitch, or roll that can invert north/up orientation.
- Terrain 3D basemap textures must keep MapLibre canvas row order (`UNPACK_FLIP_Y_WEBGL=false`); mesh `v=0` is already the north/top edge.
- Terrain 3D is behind `TERRAIN_3D_ENABLED` and defaults off; keep public 2D pages from linking to it unless that flag is intentionally enabled.

## Fast Checks
- Python unit tests: `uv run pytest tests/unit -q`
- JS unit tests: `node --test src/web/js/*.test.mjs`
- Terrain/HAND focused tests: `uv run --with rasterio --with affine --extra test python -m pytest tests/unit/test_terrain_v2_endpoint.py tests/unit/test_terrain_cog.py tests/unit/test_hand_precompute_cache.py -q`
- Prod health: `curl -s https://drose.io/floodmap/api/health | head`
- Blank-map prod smoke: use a real browser and verify `window.floodMap`, `window.floodMap.map.loaded()`, and a non-empty `#map canvas`. If the static controls/legend show but MapLibre controls do not, suspect a stale cached client asset first.
- Bare `uv run` deployments can point at external data with `FLOODMAP_DATA_ROOT=/path/to/data`; dynamic HAND COG serving needs `uv run --with rasterio --with affine ...`.
- Offline HAND generation uses the `hydrology` extra: `uv run --extra hydrology ...`. Keep large COGs and scratch output under `FLOODMAP_DATA_ROOT`/external storage, not committed in the repo.

## Where To Look Next
- Agent docs index: `docs/AGENTS.md`
