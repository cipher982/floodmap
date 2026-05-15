# ORNL CFIM v0.21 Precomputed HAND Ingest

- Region: `ornl-cfim-v0p21-huc6-031601`
- HUC: `031601`
- Source raster: `/mnt/storage/floodmap/data/hand-precomputed/ornl-cfim-v0.21/031601/031601hand.tif`
- Output COG: `/mnt/storage/floodmap/data/terrain/hand-precomputed/ornl-cfim-v0.21/031601/031601hand-u16dm.cog.tif`
- Output size: 478,064,537 bytes
- Manifest: `/mnt/storage/floodmap/data/terrain/manifests/ornl-cfim-v0p21-031601.json`
- Report manifest copy: `docs/qa/hand-precomputed/ornl-cfim-v0p21-huc6-031601/manifest.json`
- Elapsed: 174.941 seconds
- Source archive: `/mnt/storage/floodmap/data/hand-precomputed/ornl-cfim-v0.21/source-zips/031601.zip`
- Source archive size: 19,409,281,548 bytes
- Source archive SHA-256: `2e597ff6119a0fa022c446b40270f81df58a33a1394c6cfb5a530059ca456536`

## Source

- Size: 32,802 x 25,313
- CRS: `EPSG:4269`
- Bounds: `[-89.17203699369443, 32.41009257236174, -86.13481476986347, 34.7538888698995]`
- Dtype/nodata: `float32` / `-3.4028234663852886e+38`
- Tiled/blocks: `False` / `[[1, 32802]]`
- Overviews: `[]`

## Output

- Size: 32,802 x 25,313
- CRS: `EPSG:4269`
- Dtype/nodata: `uint16` / `65535.0`
- Tiled/blocks: `True` / `[[512, 512]]`
- Overviews: `[2, 4, 8, 16, 32, 64]`

## Encoded HAND Distribution

- Total cells: 830,317,026
- Valid cells: 451,460,378 (54.372%)
- Nodata cells: 378,856,648 (45.628%)
- HAND min/p50/p95/p99/max meters: 0.0 / 12.0 / 58.7 / 85.5 / 251.0

## Low-HAND Coverage

- <= 1 ft: 16,225,071 cells (3.594% of valid)
- <= 3 ft: 30,963,239 cells (6.858% of valid)
- <= 6 ft: 53,604,611 cells (11.874% of valid)
- <= 10 ft: 82,769,034 cells (18.334% of valid)
- <= 20 ft: 145,247,921 cells (32.173% of valid)
- <= 30 ft: 190,957,841 cells (42.298% of valid)
