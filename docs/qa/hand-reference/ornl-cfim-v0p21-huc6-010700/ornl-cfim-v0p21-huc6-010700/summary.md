# HAND vs FEMA NFHL: ornl-cfim-v0p21-huc6-010700

- Terrain manifest version: `ornl-cfim-v0p21-010700`
- HAND source: `/mnt/storage/floodmap/data/terrain/hand-precomputed/ornl-cfim-v0.21/010700/010700hand-u16dm.cog.tif`
- FEMA source: `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query`
- FEMA filter: `SFHA_TF = 'T'` (Special Flood Hazard Area, 1% annual chance flood hazard)
- FEMA feature count fetched: `20239`
- Rasterization: `all_touched=true`, `maxAllowableOffset=4.49156e-05 degrees` (requested ~`5m`)
- Bbox: `(-72.1425925402299, 42.19759257754596, -70.806759206189, 44.19898146749495)`

| HAND threshold | IoU | Precision | Recall | Precision lift vs random | HAND coverage | FEMA coverage | Image |
|---:|---:|---:|---:|---:|---:|---:|---|
| 1 ft | 0.320 | 0.612 | 0.402 | 6.305x | 6.37% | 9.70% | [comparison-1ft.png](comparison-1ft.png) |
| 3 ft | 0.397 | 0.599 | 0.540 | 6.172x | 8.76% | 9.70% | [comparison-3ft.png](comparison-3ft.png) |
| 6 ft | 0.439 | 0.560 | 0.671 | 5.770x | 11.62% | 9.70% | [comparison-6ft.png](comparison-6ft.png) |
| 10 ft | 0.443 | 0.505 | 0.785 | 5.200x | 15.09% | 9.70% | [comparison-10ft.png](comparison-10ft.png) |
| 20 ft | 0.372 | 0.387 | 0.904 | 3.988x | 22.66% | 9.70% | [comparison-20ft.png](comparison-20ft.png) |

Interpretation notes:

- High precision means HAND-highlighted cells usually fall inside FEMA SFHA.
- High recall means HAND captures most FEMA SFHA cells.
- Precision lift compares HAND to a same-coverage random mask; near 1.0x means the threshold is barely more selective than chance.
- HAND and FEMA are not expected to match perfectly: FEMA is regulatory floodplain mapping; HAND is a terrain-derived height-above-drainage screen.
- FEMA-negative cells are not proof of no flooding; these metrics compare against mapped effective SFHA polygons only.
