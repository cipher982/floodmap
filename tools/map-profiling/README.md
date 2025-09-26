Map Profiling Harness

What it does
- Captures HARs for consistent scenarios (cold, pan, zoom-out, warm reload).
- Analyzes totals, by host/type, and largest resources.
- Emits machine-readable metrics (JSON) and a Markdown summary per run.

Install
- cd tools/map-profiling && npm i
- Optionally install browsers: npm run install:playwright

Quick start
- Single capture: node capture-har.mjs https://your.url --width=1440 --height=900 --duration=10000 --selector='CSS'
- Analyze: node analyze-har.mjs har.json
- Suite (recommended): URL=https://your.url SELECTOR='CSS' npm run suite

Scenarios (suite)
- cold: initial load only
- pan: smooth drags across the map
- zoomout: 3 zoom-out steps, then idle
- warm: one reload within the same context

Outputs
- results/<timestamp>/har_*.json – raw HAR files
- results/<timestamp>/*.metrics.json – metrics per HAR
- results/<timestamp>/summary.(json|md) – summary across scenarios
- results/<timestamp>/meta.json – URL, viewport, commit hash

Notes
- All runs use a fresh browser context (no prior cache) except the warm scenario (reload within the same context).
- The harness captures actual transferred bytes (compressed) and groups elevation/vector tiles by zoom level.
