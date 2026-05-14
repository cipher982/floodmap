# HUC-Scale HAND Gate: 0312 Ochlockonee

- Automated result: **PASS**.
- Visual boundary-artifact review: **PASS with caveat**. Preview shows coherent
  dendritic drainage and coastal lowland structure, with no obvious internal
  seam/fan artifact like the early prototype. The COG is still rectangular-bbox
  based, not clipped to the HUC polygon.
- Region states: `FL,GA`.
- WBD area: `9,834.86 km^2`.
- Bbox: `(-84.98580749501282, 29.890844392606933, -83.76342334260326, 31.48889304914836)`.
- DEM resolution: `10m`.
- Drain params: burn `5.0m`, accumulation `16.0 km^2`.
- Source COG: `/mnt/storage/floodmap/data/terrain/hand/huc4-0312-ochlockonee.tif`.
- Scratch artifacts: `/mnt/storage/floodmap/scratch/hand-huc-scale/huc4-0312-ochlockonee`.

## Measured Gate Metrics

| Metric | Value | Threshold | Pass |
|---|---:|---:|---:|
| Wall time | 809.6s | 10800s | True |
| Peak RSS | 16506.0 MB | 24576 MB | True |
| Source COG | 193.1 MB | 500.0 MB | True |
| Valid HAND cells | 95.38% | report-only | n/a |
| 3ft area | 17.55% | report-only | n/a |

## Pre-Run Size Estimate

- Projected bbox grid: `13,763 x 19,052` cells.
- Bbox cells: `262,212,676`.
- Raw uint16 bbox bytes: `524.4 MB` before compression and overviews.

## Interpretation

- This gate measures the current bbox-based prototype path. It does not prove that large HUC4s can run without regional tiling.
- A pass means one small real HUC4 can fit the current approach. A fail means the CONUS path must be tiled before any national batch.
- Next architecture constraint: CONUS regions need polygon clipping or a tiled
  mosaic rule, because HUC4 bboxes include valid-looking terrain outside the
  actual watershed.
