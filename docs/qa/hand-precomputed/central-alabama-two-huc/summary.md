# Central Alabama Two-HUC ORNL HAND Review

- Dataset version: `ornl-cfim-v0p21-central-alabama`
- Regions: `031601` then `031501`
- Manifest on Cube: `/mnt/storage/floodmap/data/terrain/manifests/ornl-cfim-v0p21-central-alabama.json`
- Review server: `http://100.125.140.78:18000/?lat=33.5186&lng=-86.8104&zoom=10.2&view=hand&water=1000&handGpu=1`

## What changed

Added ORNL HUC6 `031501` beside the validated Birmingham `031601` COG. The
terrain API now serves a two-region manifest and mosaics tiles across both
regions, filling nodata from later regions where possible.

## QA

- API metadata reports two HAND regions.
- GPU renderer loaded 30 resident HAND textures at the review viewport with no
  tile load errors.
- At `1000m`, valid pixels from both HUCs are visible, and the broad east-side
  coverage is expanded.
- Mountain Brook, Vestavia Hills, Hoover, and Trussville point samples still
  return no-data. That means the central white strip is not solved by `031501`;
  it likely needs a missing adjacent HUC, or ORNL CFIM masks those uplands out
  in this product.

Screenshot: `max1000-gpu-review.jpg`.
