# ORNL CFIM v0.21 Precomputed HAND Ingest

- Region: `ornl-cfim-v0p21-huc6-010700`
- HUC: `010700`
- Source raster: `/mnt/storage/floodmap/data/hand-precomputed/ornl-cfim-v0.21/010700/010700hand.tif`
- Output COG: `/mnt/storage/floodmap/data/terrain/hand-precomputed/ornl-cfim-v0.21/010700/010700hand-u16dm.cog.tif`
- Output size: 172,578,583 bytes
- Manifest: `/mnt/storage/floodmap/data/terrain/manifests/ornl-cfim-v0p21-010700.json`
- Report manifest copy: `docs/qa/hand-precomputed/ornl-cfim-v0p21-huc6-010700/manifest.json`
- Elapsed: 51.054 seconds

## Source

- Size: 14,427 x 21,615
- CRS: `EPSG:4269`
- Bounds: `[-72.1425925402299, 42.19759257754596, -70.806759206189, 44.19898146749495]`
- Dtype/nodata: `float32` / `-3.4028234663852886e+38`
- Tiled/blocks: `False` / `[[1, 14427]]`
- Overviews: `[]`

## Output

- Size: 14,427 x 21,615
- CRS: `EPSG:4269`
- Dtype/nodata: `uint16` / `65535.0`
- Tiled/blocks: `True` / `[[512, 512]]`
- Overviews: `[2, 4, 8, 16, 32, 64]`

## Encoded HAND Distribution

- Total cells: 311,839,605
- Valid cells: 167,329,470 (53.659%)
- Nodata cells: 144,510,135 (46.341%)
- HAND min/p50/p95/p99/max meters: 0.0 / 22.2 / 161.8 / 342.0 / 1033.9

## Low-HAND Coverage

- <= 1 ft: 10,664,110 cells (6.373% of valid)
- <= 3 ft: 14,650,515 cells (8.755% of valid)
- <= 6 ft: 19,448,562 cells (11.623% of valid)
- <= 10 ft: 25,248,319 cells (15.089% of valid)
- <= 20 ft: 38,303,314 cells (22.891% of valid)
- <= 30 ft: 49,163,075 cells (29.381% of valid)
