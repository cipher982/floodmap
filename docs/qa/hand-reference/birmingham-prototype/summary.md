# HAND vs FEMA NFHL: birmingham-prototype

- Terrain manifest version: `hand-houston-20260514a`
- HAND source: `/mnt/storage/floodmap/data/terrain/hand/birmingham-drainage.tif`
- FEMA source: `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query`
- FEMA filter: `SFHA_TF = 'T'` (Special Flood Hazard Area, 1% annual chance flood hazard)
- FEMA feature count fetched: `2560`
- Rasterization: `all_touched=true`, `maxAllowableOffset=5.0m`
- Bbox: `(-87.02, 33.3, -86.52, 33.75)`

| HAND threshold | IoU | Precision | Recall | Precision lift vs random | HAND coverage | FEMA coverage | Image |
|---:|---:|---:|---:|---:|---:|---:|---|
| 3 ft | 0.312 | 0.590 | 0.398 | 8.896x | 4.47% | 6.63% | [comparison-3ft.png](comparison-3ft.png) |
| 6 ft | 0.379 | 0.536 | 0.563 | 8.087x | 6.96% | 6.63% | [comparison-6ft.png](comparison-6ft.png) |
| 10 ft | 0.399 | 0.474 | 0.718 | 7.144x | 10.05% | 6.63% | [comparison-10ft.png](comparison-10ft.png) |

Interpretation notes:

- High precision means HAND-highlighted cells usually fall inside FEMA SFHA.
- High recall means HAND captures most FEMA SFHA cells.
- Precision lift compares HAND to a same-coverage random mask; near 1.0x means the threshold is barely more selective than chance.
- HAND and FEMA are not expected to match perfectly: FEMA is regulatory floodplain mapping; HAND is a terrain-derived height-above-drainage screen.
- FEMA-negative cells are not proof of no flooding; these metrics compare against mapped effective SFHA polygons only.
