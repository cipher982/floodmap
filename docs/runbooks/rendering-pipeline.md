# Rendering Pipeline Notes

## Modes
- `elevation` mode: hypsometric tint (global nonlinear `asinh` mapping).
- `flood` mode: compare elevation vs slider water level; NODATA treated as water.

## Fast path (common)
- Elevation tiles are fetched as `.u16` and rendered in `src/web/js/render-worker.js` using a 65,536-entry LUT (`Uint32Array`).
- Worker tries OffscreenCanvas PNG encoding; otherwise it returns raw pixel buffers for main-thread encoding.

## Key files
- Map + protocol + worker wiring: `src/web/js/map-client.js`
- Elevation fetch + caches: `src/web/js/elevation-renderer.js`
- Worker + LUT/palette: `src/web/js/render-worker.js`
