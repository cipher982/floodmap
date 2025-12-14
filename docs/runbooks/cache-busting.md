# Cache-Busting (Frontend + Tiles)

## What caches what
- Cloudflare caches `GET` tile responses (often `immutable` for existing precompressed tiles).
- MapLibre caches tiles by URL; query-string changes are the safe “cache key”.

## When to bump versions
- After repairing DEM data or regenerating precompressed tiles, bump the elevation tile fetch `v=...`.
- When changing JS/CSS, bump the static asset `?v=...` in `src/web/index.html`.

## Where versions live (currently)
- `src/web/index.html` script/style `?v=...`
- `src/web/js/elevation-renderer.js` → `qs.set('v', '...')`
- `src/web/js/map-client.js` → worker URL `render-worker.js?v=...`
