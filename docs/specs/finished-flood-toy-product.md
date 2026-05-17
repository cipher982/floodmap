# Finished Flood Toy Product Goal

FloodMap should be a real-world flood toy, not a GIS research page.

The finished product promise is:

> Search any U.S. place, raise the water, and watch animated water fill real
> valleys, streets, creek corridors, and low ground on a pannable map.

## Success Criteria

- The public map path opens directly into a real map with street/vector tiles,
  place labels, water features, and terrain-backed flood toy controls.
- Search, direct city pages, ZIP pages, and share links all land on the same
  national engine. City pages may set camera defaults only; they must not use
  per-city rendering hacks.
- Flood Toy mode uses real terrain/HAND data where coverage exists and gives a
  clear fallback when coverage is missing.
- Slider input updates water while dragging and does not re-render tiles for
  every slider position on the GPU path.
- Water looks fun: animated edges, current streaks, depth color, and visible
  motion that follows real terrain gradients.
- The experience remains honest: it is an exploratory visual toy, not a
  forecast, FEMA map, insurance product, or emergency-planning model.
- The map stays readable at low, medium, and extreme water levels.

## QA Contract

Automated QA must prove the product without a human reviewer:

- Load a real map URL with `view=hand` and GPU rendering enabled.
- Confirm real HAND metadata and real HAND tile textures are loaded.
- Capture map screenshots at low, medium, and high water levels.
- Assert the low-to-high screenshots change substantially.
- Confirm the animated layer keeps repainting after the map is idle.
- Pan the map, wait for terrain to refill, and capture a panned screenshot.
- Build and reload a share URL, then verify the view mode and water level round
  trip.
- Fail on console errors, page errors, failed requests, or HTTP 4xx/5xx
  responses.
- Record pass/fail, screenshots, visual-difference metrics, and GPU stats in a
  machine-readable summary.

## Next Frontier

The current real-map layer is a GPU-rendered 2D flood toy. The next major leap
is a bounded 3D/WebGPU terrain sandbox over the current map view, using the
same real terrain/HAND sources as initial conditions.
