# Cache-Busting (Frontend + Tiles)

## What caches what
- Cloudflare caches `GET` tile responses (often `immutable` for existing precompressed tiles).
- MapLibre caches tiles by URL; query-string changes are the safe “cache key”.

## Unified versioning (preferred)
Floodmap uses a single version string to bust caches end-to-end:
- `window.FLOODMAP_ASSET_VERSION` in `src/web/index.html` (edit this one value)

`index.html` injects Floodmap-owned CSS/JS with `?v=<ASSET_VERSION>`, and runtime URLs derive from it:
- Worker URL: `render-worker.js?v=<ASSET_VERSION>`
- Elevation tile fetch: `...u16?method=precompressed&v=<TILE_VERSION>`

## Tiles-only busting (optional)
If you repair DEM data / regenerate tiles but don’t want to change frontend assets, you can set
tile version independently for a session:
- `https://drose.io/floodmap/?tile_v=202512xx`

This sets:
- `window.FLOODMAP_TILE_VERSION = tile_v || FLOODMAP_ASSET_VERSION`

## When to bump what
- Frontend changes (JS/CSS/worker): bump `FLOODMAP_ASSET_VERSION`
- Data repairs / tile regen only: prefer `?tile_v=...` (or bump `FLOODMAP_ASSET_VERSION` if you want a global reset)
