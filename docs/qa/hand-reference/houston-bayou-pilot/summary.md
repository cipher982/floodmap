# HAND vs FEMA NFHL: houston-bayou-pilot

- Terrain manifest version: `hand-houston-20260514a`
- HAND source: `/mnt/storage/floodmap/data/terrain/hand/houston-bayou-pilot.tif`
- FEMA source: `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query`
- FEMA filter: `SFHA_TF = 'T'` (Special Flood Hazard Area, 1% annual chance flood hazard)
- FEMA feature count fetched: `5997`
- Rasterization: `all_touched=true`, `maxAllowableOffset=5.0m`
- Bbox: `(-95.82, 29.45, -94.95, 30.15)`

| HAND threshold | IoU | Precision | Recall | Precision lift vs random | HAND coverage | FEMA coverage | Image |
|---:|---:|---:|---:|---:|---:|---:|---|
| 3 ft | 0.210 | 0.311 | 0.394 | 1.241x | 31.72% | 25.11% | [comparison-3ft.png](comparison-3ft.png) |
| 6 ft | 0.235 | 0.282 | 0.585 | 1.124x | 52.07% | 25.11% | [comparison-6ft.png](comparison-6ft.png) |
| 10 ft | 0.252 | 0.275 | 0.750 | 1.096x | 68.44% | 25.11% | [comparison-10ft.png](comparison-10ft.png) |

Interpretation notes:

- High precision means HAND-highlighted cells usually fall inside FEMA SFHA.
- High recall means HAND captures most FEMA SFHA cells.
- Precision lift compares HAND to a same-coverage random mask; near 1.0x means the threshold is barely more selective than chance.
- HAND and FEMA are not expected to match perfectly: FEMA is regulatory floodplain mapping; HAND is a terrain-derived height-above-drainage screen.
- FEMA-negative cells are not proof of no flooding; these metrics compare against mapped effective SFHA polygons only.
