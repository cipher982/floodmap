# Gate 10 Decision: ORNL CFIM v0.21 HUC6 010700

Decision: pass for product-direction validation.

## Why It Passes

- FEMA SFHA fetch/rasterization completed without manual GIS steps.
- FEMA feature count: `20,239` SFHA polygons fetched; `2` empty/invalid
  geometries skipped.
- The visual panels show coherent drainage corridors rather than random lowland
  noise.
- Every tested HAND threshold has precision lift versus a same-coverage random
  mask well above the `2.0x` gate:
  - `1ft`: `6.305x`
  - `3ft`: `6.172x`
  - `6ft`: `5.770x`
  - `10ft`: `5.200x`
  - `20ft`: `3.988x`
- Best balanced thresholds:
  - `6ft`: IoU `0.439`, precision `0.560`, recall `0.671`
  - `10ft`: IoU `0.443`, precision `0.505`, recall `0.785`
- The low-elevation baseline check also passes. ORNL HAND beats a
  same-coverage lowest-absolute-elevation mask by:
  - `1ft`: `2.219x`
  - `3ft`: `2.488x`
  - `6ft`: `2.594x`
  - `10ft`: `2.410x`
  - `20ft`: `2.063x`
- The `all_touched=false` sensitivity run is stable:
  - `6ft`: IoU `0.432`, precision `0.533`, recall `0.695`,
    low-elevation lift `2.681x`
  - `10ft`: IoU `0.425`, precision `0.474`, recall `0.802`,
    low-elevation lift `2.457x`

## Product Interpretation

This supports the pivot from "flood map" to "drainage-relative terrain map."
ORNL HAND is not a flood-probability layer, but in this pilot it is strongly
selective for FEMA-mapped flood hazard corridors compared with random land
coverage.

The user-facing slider can be useful if it is described as:

> land within N feet of local drainage

not:

> land that will flood at N feet

## Caveats

- FEMA NFHL is a regulatory floodplain reference, not a complete flooding ground
  truth layer.
- HAND-only cells are not automatically false positives; they may be unmapped
  drainage-adjacent terrain, smaller streams, wetlands, or low areas outside
  effective FEMA SFHA.
- FEMA-only cells are not automatically ORNL failures; FEMA modeling can include
  coastal, backwater, hydraulic, or mapped-regulatory effects not represented by
  a simple HAND threshold.
- This is one HUC6. The next product-risk pilot should be Birmingham's inland
  storm-prone drainage geography, not another convenient New England unit.
- About half of FEMA raster cells in the HUC6 bbox fall outside the valid ORNL
  HAND footprint (`48.98%` with `all_touched=true`, `49.50%` with
  `all_touched=false`). The current metrics correctly compare inside valid HAND
  cells only, but cross-region comparisons need HUC polygon coverage rather than
  bbox-only context.

## Next Gate

Run the same ORNL-vs-FEMA validation for the HUC6 containing Birmingham, then
compare the product story:

- Does ORNL HAND make Village Creek / Valley Creek / Five Mile Creek visually
  obvious?
- Does the best threshold remain meaningfully above random baseline?
- Does the map explain inland storm-prone terrain better than absolute
  elevation?
