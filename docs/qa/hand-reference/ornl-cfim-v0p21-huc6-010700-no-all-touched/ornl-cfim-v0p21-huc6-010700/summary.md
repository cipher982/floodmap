# HAND vs FEMA NFHL: ornl-cfim-v0p21-huc6-010700

- Terrain manifest version: `ornl-cfim-v0p21-010700`
- HAND source: `/mnt/storage/floodmap/data/terrain/hand-precomputed/ornl-cfim-v0.21/010700/010700hand-u16dm.cog.tif`
- FEMA source: `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query`
- FEMA filter: `SFHA_TF = 'T'` (Special Flood Hazard Area, 1% annual chance flood hazard)
- FEMA feature count fetched: `20239`
- FEMA raster cells: `29561848`; in HAND nodata: `14632411`
- Rasterization: `all_touched=false`, `maxAllowableOffset=4.49156e-05 degrees` (requested ~`5m`)
- Low-elevation baseline raster: `/mnt/storage/floodmap/data/hand-precomputed/ornl-cfim-v0.21/010700/010700-elevation.tif`
- Bbox: `(-72.1425925402299, 42.19759257754596, -70.806759206189, 44.19898146749495)`

| HAND threshold | IoU | Precision | Recall | Lift vs random | Lift vs low elev | HAND coverage | FEMA coverage | Image |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 ft | 0.333 | 0.600 | 0.428 | 6.720x | 2.346x | 6.37% | 8.92% | [comparison-1ft.png](comparison-1ft.png) |
| 3 ft | 0.402 | 0.579 | 0.568 | 6.492x | 2.601x | 8.76% | 8.92% | [comparison-3ft.png](comparison-3ft.png) |
| 6 ft | 0.432 | 0.533 | 0.695 | 5.975x | 2.681x | 11.62% | 8.92% | [comparison-6ft.png](comparison-6ft.png) |
| 10 ft | 0.425 | 0.474 | 0.802 | 5.316x | 2.457x | 15.09% | 8.92% | [comparison-10ft.png](comparison-10ft.png) |
| 20 ft | 0.347 | 0.359 | 0.911 | 4.022x | 2.081x | 22.66% | 8.92% | [comparison-20ft.png](comparison-20ft.png) |

Interpretation notes:

- `maxAllowableOffset` is requested as meters and converted to CRS units for the FEMA service.
- High precision means HAND-highlighted cells usually fall inside FEMA SFHA.
- High recall means HAND captures most FEMA SFHA cells.
- Precision lift compares HAND to a same-coverage random mask; near 1.0x means the threshold is barely more selective than chance.
- Low-elevation lift, when present, compares HAND to the same number of lowest absolute-elevation cells.
- HAND and FEMA are not expected to match perfectly: FEMA is regulatory floodplain mapping; HAND is a terrain-derived height-above-drainage screen.
- FEMA-negative cells are not proof of no flooding; these metrics compare against mapped effective SFHA polygons only.
