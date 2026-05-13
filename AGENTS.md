# Floodmap (drose.io/floodmap) - Agent Quickstart

FastAPI serves the public app and tile APIs for `https://drose.io/floodmap`.
The browser owns MapLibre rendering: it fetches vector tiles plus raw elevation
tiles and colors them client-side.

## Non-Negotiables
- Never create/overwrite `.env` (ask before appending).
- Prefer project tooling: `uv run ...` (do not assume `python` exists).
- Avoid `docker wait` (can hang).
- "Shipped" means live in production. Do not describe local-only commits or unpushed changes as shipped; if it is not deployed, say so plainly.
- Any user-visible JS/CSS/worker change, or global tile-cache reset, must bump `ASSET_VERSION` in `src/api/page_renderer.py` before shipping. `src/web/index.html` contains the placeholder, not the source of truth.
- Preserve the custom Umami events in `src/web/js/map-client.js` (`location_click`, `viewport_view`) when touching analytics or map event code.

## Fast Checks
- Python unit tests: `uv run pytest tests/unit -q`
- JS unit test: `node --test src/web/js/render-worker.test.mjs`
- Prod health: `curl -s https://drose.io/floodmap/api/health | head`
- Blank-map prod smoke: use a real browser and verify `window.floodMap`, `window.floodMap.map.loaded()`, and a non-empty `#map canvas`. If the static controls/legend show but MapLibre controls do not, suspect a stale cached client asset first.

## Where To Look Next
- Agent docs index: `docs/AGENTS.md`
