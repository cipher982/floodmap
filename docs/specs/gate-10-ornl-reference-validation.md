# Gate 10: ORNL HAND External Reference Validation

Status: in progress

## Decision

Gate 9 proved that ORNL CFIM HAND can be ingested and served by Floodmap. Gate
10 decides whether it is product-meaningful enough to scale.

The reference is FEMA NFHL Special Flood Hazard Area (`SFHA_TF = 'T'`). FEMA is
not ground truth for all flooding, but it is the right first external benchmark:
it is national, regulatory, and independent from our HAND pipeline.

## Inputs

- ORNL CFIM v0.21 HUC6 `010700` manifest:
  `/mnt/storage/floodmap/data/terrain/manifests/ornl-cfim-v0p21-010700.json`
- ORNL COG:
  `/mnt/storage/floodmap/data/terrain/hand-precomputed/ornl-cfim-v0.21/010700/010700hand-u16dm.cog.tif`
- FEMA NFHL Flood Hazard Zones service layer `28`
- Existing comparison tool: `tools/hand/compare_to_reference.py`

## Task List

1. Run the ORNL HUC6 `010700` COG against FEMA NFHL SFHA polygons.
2. Generate metrics at `1ft`, `3ft`, `6ft`, `10ft`, and `20ft`.
3. Generate same-grid visual panels for each threshold.
4. Record the FEMA feature count, rasterization settings, and any service/cache
   limitations.
5. Make a gate decision in `docs/qa/hand-reference/ornl-cfim-v0p21-huc6-010700/`.
6. If Gate 10 passes, pick the next ORNL HUC6 by product risk, not convenience:
   Birmingham/inland storm-prone terrain first.

## Success Criteria

Gate 10 passes if all are true:

- FEMA fetch and rasterization complete without manual GIS steps.
- Visual panels show coherent drainage corridors with no obvious tile, bbox, or
  HUC-boundary artifact.
- At least one practical HAND threshold has precision lift vs random `>= 2.0x`.
- The best threshold has a clear product interpretation that can be explained in
  public copy without claiming forecast flood probability.
- Browser review remains usable at z12 with the ORNL manifest.

Gate 10 fails if:

- FEMA coverage is too sparse or inconsistent to judge the pilot.
- HAND threshold masks look like generic lowland blobs without drainage meaning.
- Precision lift stays near `1.0x` across practical thresholds.
- The only honest copy would be so caveated that the product loses its hook.
