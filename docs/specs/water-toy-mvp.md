# Water Toy MVP

Status: active
Owner: Codex

## Product Frame

Floodmap should feel like a toy before it feels like a study. The first-run
experience is:

> Search a real place, drag the water up, and watch the map flood.

The app can keep honest caveats in secondary copy, but the primary surface should
not lead with drainage-analysis language.

## Goal

Turn the ORNL HAND layer from a static terrain overlay into a playful flood
reveal:

- the slider stays powerful and high-range values remain available
- selected low-HAND areas render as animated water, not flat color
- the flood edge is visually alive while the slider moves
- copy and controls use fun language instead of scientific vocabulary

This is a visual scenario toy, not a forecast, FEMA product, insurance product,
or emergency tool.

## Non-Goals

- Do not build a full Three.js terrain engine in this first slice.
- Do not remove high slider values.
- Do not invent new hydrology or generated "AI-upscaled" data.
- Do not break the existing worker fallback path.
- Do not precompute threshold-specific rendered tiles.

## MVP Implementation

Use the existing `FloodmapHandGpuLayer` as the first water renderer:

1. Add an animated shader mode for HAND tiles.
2. Use `raw <= threshold` as the water mask.
3. Render masked pixels as blue animated water with shimmer/noise.
4. Color water by apparent depth, `threshold - raw`, so higher slider values
   feel more dramatic.
5. Detect pixels near the active threshold and render a brighter moving foam
   edge.
6. Drive animation with a gated `requestAnimationFrame` repaint loop only while
   the GPU layer is active.
7. Use world/mercator-space shader noise so animation does not visibly tile at
   256px boundaries.
8. Keep the foam edge as a value band around the threshold; do not add
   neighbor-sampling shoreline detection in v1.
9. Keep NODATA transparent unless the debug flag is enabled.
10. Keep slider updates as uniform-only GPU repaints.
11. Leave the CPU/worker HAND renderer as the fallback visual path.

## UI Changes

Primary copy should become toy-first:

- Mode label: `Flood Toy` or `Water Toy`
- Slider label: `Raise the water`
- Display value: primary fun label, secondary meter value
- Presets: `Puddle`, `Street Flood`, `Neighborhood`, `City Flood`,
  `Apocalypse`
- Click panel title in this mode: `Flood Check`

Secondary caveat copy:

> Visual scenario powered by terrain/drainage data. Not a forecast.

## Success Criteria

- In HAND/GPU mode, dragging the slider visibly animates water and foam without
  tile URL churn or worker renders.
- The map still shows streets and labels above the water effect.
- High slider values remain available and look like a dramatic flood reveal, not
  a washed-out topographic layer.
- Existing elevation and old flood modes still work.
- GPU fallback remains possible if WebGL2 integer textures are unavailable.
- JS unit tests pass.
- Python unit tests pass.
- Browser QA captures at least one screenshot with visible animated water at
  Birmingham.

## Later

After this MVP feels good:

- Add a play/pause flood animation control.
- Add a Three.js tilt/terrain mode.
- Add local "before/after" share cards.
- Add named-place flood presets for social sharing.
