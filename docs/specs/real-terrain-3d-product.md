# Real Terrain 3D FloodMap Product

The final product is a real-world flood toy where the map itself becomes a 3D
terrain surface.

The user-facing mental model:

> Search a real place, raise the water, and watch water move through a textured
> 3D miniature of that city.

## Architecture

- The 2D street/vector map is rendered first and captured as a texture.
- Real elevation data displaces that texture into a terrain mesh. Prefer ORNL
  CFIM elevation rasters through the v2 terrain manifest; use legacy v1
  elevation tiles only as a fallback.
- ORNL CFIM HAND data initializes creek, drainage, and flood water over the
  terrain.
- The public 2D map remains the fallback and navigation shell.
- The 3D engine owns spectacle: camera, terrain relief, animated water, and
  eventually physics spillover.

HAND is not the final water boundary. HAND is the initializer. A finished
physics engine can push water past the initial HAND threshold when the local
terrain and simulated water surface make that plausible.

## Milestone 1

Build a reviewable 3D scene for a real map tile:

- Load a real MapLibre vector basemap for the selected tile.
- Capture the map canvas and drape it over a WebGL terrain mesh.
- Load matching elevation and HAND tiles.
- Render animated water above the terrain where HAND is within the selected
  level.
- Publish browser-readable stats for QA.
- Keep the existing 2D Flood Toy path intact.

This is not yet the final physics engine. It is the first integrated product
surface where the terrain, basemap, and HAND water exist in one GPU-rendered 3D
view.

## Acceptance Criteria

- `/terrain-3d` and `/floodmap/terrain-3d` serve the 3D review app.
- The scene opens centered on a real place and can be adjusted through URL
  parameters: `lat`, `lng`, `zoom`, `water`, `exaggeration`.
- The rendered canvas is nonblank and visually rich.
- The basemap texture is visible on the terrain surface.
- Water is visible when HAND is below the selected water level.
- The water animation changes frame-to-frame while the camera is idle.
- Browser QA records screenshots, stats, and failures.
- JS/Python tests and CI pass.

## Next Milestone

Replace threshold water with a stateful viewport simulation:

- Use HAND as source pressure and drainage hints.
- Use elevation as bed height.
- Run bounded WebGPU shallow-water steps in the active viewport.
- Allow water to spill beyond the initial HAND mask.
- Read no large generated data from the repo; stream existing tiles.

## Polish Milestone

The public 3D path should look like a product showcase, not a debug harness:

- The canvas owns the full viewport.
- Default UI is a compact overlay; JSON stats are hidden unless `debug=1`.
- Terrain uses full-resolution sampling and softened relief so roads, valleys,
  and water remain readable.
- Browser QA must fail if the debug panel/sidebar returns to the default view.
