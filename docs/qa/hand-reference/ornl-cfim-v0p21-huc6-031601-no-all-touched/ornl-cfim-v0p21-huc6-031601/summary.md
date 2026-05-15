# HAND vs FEMA NFHL: ornl-cfim-v0p21-huc6-031601

- Terrain manifest version: `ornl-cfim-v0p21-031601`
- HAND source: `/mnt/storage/floodmap/data/terrain/hand-precomputed/ornl-cfim-v0.21/031601/031601hand-u16dm.cog.tif`
- FEMA source: `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query`
- FEMA filter: `SFHA_TF = 'T'` (Special Flood Hazard Area, 1% annual chance flood hazard)
- FEMA feature count fetched: `12245`
- FEMA raster cells: `124753511`; in HAND nodata: `54324122`
- Rasterization: `all_touched=false`, `maxAllowableOffset=4.49156e-05 degrees` (requested ~`5m`)
- Low-elevation baseline raster: `/mnt/storage/floodmap/data/hand-precomputed/ornl-cfim-v0.21/031601/031601-elevation.tif`
- Bbox: `(-89.17203699369443, 32.41009257236174, -86.13481476986347, 34.7538888698995)`

| HAND threshold | IoU | Precision | Recall | Lift vs random | Lift vs low elev | HAND coverage | FEMA coverage | Image |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 ft | 0.137 | 0.645 | 0.149 | 4.137x | 0.776x | 3.59% | 15.60% | [comparison-1ft.png](comparison-1ft.png) |
| 3 ft | 0.233 | 0.618 | 0.272 | 3.964x | 0.918x | 6.86% | 15.60% | [comparison-3ft.png](comparison-3ft.png) |
| 6 ft | 0.343 | 0.591 | 0.450 | 3.791x | 1.095x | 11.87% | 15.60% | [comparison-6ft.png](comparison-6ft.png) |
| 10 ft | 0.424 | 0.551 | 0.647 | 3.530x | 1.226x | 18.33% | 15.60% | [comparison-10ft.png](comparison-10ft.png) |
| 20 ft | 0.422 | 0.442 | 0.902 | 2.836x | 1.253x | 31.79% | 15.60% | [comparison-20ft.png](comparison-20ft.png) |

Interpretation notes:

- `maxAllowableOffset` is requested as meters and converted to CRS units for the FEMA service.
- High precision means HAND-highlighted cells usually fall inside FEMA SFHA.
- High recall means HAND captures most FEMA SFHA cells.
- Precision lift compares HAND to a same-coverage random mask; near 1.0x means the threshold is barely more selective than chance.
- Low-elevation lift, when present, compares HAND to the same number of lowest absolute-elevation cells.
- HAND and FEMA are not expected to match perfectly: FEMA is regulatory floodplain mapping; HAND is a terrain-derived height-above-drainage screen.
- FEMA-negative cells are not proof of no flooding; these metrics compare against mapped effective SFHA polygons only.
