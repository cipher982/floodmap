# Whitebox HAND Unit: HUC8 01070006 Merrimack River

- Output: `/mnt/storage/floodmap/data/terrain/hand/huc8-01070006-merrimack-river-buffer5km-clipped-whitebox-eas.tif`.
- Wall time: `167.06s` (True).
- Peak RSS: `18209.3 MB` (True).
- Source COG: `11.2 MB` (True).
- Selected flowlines: `26168`; stream cells: `1323570`.
- Valid cells: `4935772` of `143755272` (`3.43%`).
- 3ft/6ft/10ft area: `23.18%` / `30.36%` / `37.96%`.
- p50/p95/p99 HAND: `5.757` / `53.008` / `99.29` m.

Caveat: this is a native-engine smoke rejector, not a production acceptance test. It uses a rasterized mapped-flowline stream mask and raw DEM routing, so a pass would still need drainage-definition and conditioning parity before CONUS batching.
