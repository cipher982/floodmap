# Birmingham HAND Prototype QA

## Model
- Source DEM: USGS 3DEP via py3dep, 10m target resolution.
- Source drainage: NHDPlus HR flowlines queried for bbox `(-87.02, 33.3, -86.52, 33.75)`.
- Selected mapped drainage: named flowlines or stream order >= 2.
- Routing: pyflwdir D8 flow directions from a stream-burned DEM.
- Drain mask: selected NHDPlus HR mapped drainage OR flow accumulation >= 1.0 km².
- Derived layer: flow-path HAND, `height = DEM elevation - first downstream drain elevation`.
- This is a prototype HAND-style terrain screen, not a forecast, FEMA product, or storm-drain model.

## Coverage
- DEM grid: `5423 x 5820` cells.
- Selected flowlines: `2184`.
- Drain cells: `296195`.
- Tile counts: `{'9': 2, '10': 6, '11': 16, '12': 49}`.

## Threshold Area
| Slider | Area cells | Percent of valid HAND cells |
|---:|---:|---:|
| 1 ft | 772609 | 2.49% |
| 3 ft | 1353355 | 4.37% |
| 6 ft | 2140028 | 6.9% |
| 10 ft | 3112299 | 10.04% |
| 20 ft | 5342292 | 17.23% |
| 30 ft | 7392504 | 23.85% |

## Named Drainage Sample
```json
{
  "460": 591,
  "558": 192,
  "Cahaba River": 101,
  "Shades Creek": 59,
  "Fivemile Creek": 58,
  "Village Creek": 53,
  "Turkey Creek": 48,
  "Black Creek": 43,
  "North Fork Yellowleaf Creek": 42,
  "Valley Creek": 38,
  "Little Cahaba River": 35,
  "Dry Creek": 35,
  "Shoal Creek": 34,
  "Cane Creek": 32,
  "Cunningham Creek": 28,
  "Stinking Creek": 26
}
```

## Visual Review Checklist
- Low-height bands should trace named creek corridors, not the whole city.
- Increasing the slider from 1ft to 10ft should widen corridors gradually.
- At 20-30ft the layer should reveal valley structure, not a sea-level bathtub.
- Remaining risk: 10m DEM + NHDPlus HR do not model storm sewers, undersized culverts, blocked drains, or pluvial street flooding.
