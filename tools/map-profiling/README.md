Map Profiling Harness

What it does
- Captures HARs for consistent scenarios (cold, pan, zoom-out, warm reload).
- Profiles slider runtime costs (worker jobs, long tasks, frame gaps, CDP metrics).
- Analyzes totals, by host/type, and largest resources.
- Emits machine-readable metrics (JSON) and a Markdown summary per run.

Install
- cd tools/map-profiling && npm i
- Optionally install browsers: npm run install:playwright

Quick start
- Single capture: node capture-har.mjs https://your.url --width=1440 --height=900 --duration=10000 --selector='CSS'
- Analyze: node analyze-har.mjs har.json
- Suite (recommended): URL=https://your.url SELECTOR='CSS' npm run suite
- Slider profiler: URL=https://your.url npm run slider -- --scenario=both
- City-jump profiler: URL=https://your.url npm run city-jumps
- Explicit city pair: URL=https://your.url npm run city-jumps -- --pair='ny/new-york:tx/houston'

Scenarios (suite)
- cold: initial load only
- pan: smooth drags across the map
- zoomout: 3 zoom-out steps, then idle
- warm: one reload within the same context

City-jump profiler
- Loads one city viewport, then `flyTo(...)` jumps to another city at its default zoom.
- Records blank-screen ratio in the center of the map from screenshots, first tile timings, tile-loaded completion, and transfer totals by elevation/vector.
- Uses the curated city defaults from `src/api/location_catalog.py`.
- Outputs: `results/<timestamp>-city-jumps/summary.(json|md)`

Outputs
- results/<timestamp>/har_*.json – raw HAR files
- results/<timestamp>/*.metrics.json – metrics per HAR
- results/<timestamp>/summary.(json|md) – summary across scenarios
- results/<timestamp>/meta.json – URL, viewport, commit hash
- results/<timestamp>-slider/*.json – slider runtime metrics

Notes
- All runs use a fresh browser context (no prior cache) except the warm scenario (reload within the same context).
- The harness captures actual transferred bytes (compressed) and groups elevation/vector tiles by zoom level.
