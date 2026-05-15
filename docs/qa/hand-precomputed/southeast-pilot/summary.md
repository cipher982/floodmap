# Southeast ORNL HAND Pilot

- Dataset version: `ornl-cfim-v0p21-southeast-pilot`
- Regions: `031601`, `031501`, `031300`, `030701`, `030501`
- Manifest on Cube: `/mnt/storage/floodmap/data/terrain/manifests/ornl-cfim-v0p21-southeast-pilot.json`
- Review URL: `http://100.125.140.78:18000/?lat=33.5186&lng=-86.8104&zoom=10.2&view=hand&water=1000&handGpu=1`

## Converted COGs

| HUC6 | COG bytes |
|---|---:|
| `031601` | 478,064,537 |
| `031501` | 459,239,072 |
| `031300` | 474,466,601 |
| `030701` | 333,086,451 |
| `030501` | 478,865,850 |

Current ORNL v0.21 converted COG directory on Cube is `2.3G`, including the
earlier Merrimack `010700` pilot.

## QA

- Server smoke passed for health, vector tile, HAND metadata, HAND sample, and
  HAND tile.
- Browser smoke at Birmingham with `handGpu=1` reported GPU active, no tile load
  errors, stable `client://hand/{z}/{x}/{y}` tile URL, and 5-region coverage
  label.
- Mountain Brook, Vestavia Hills, Hoover, and Trussville still return no-data
  point samples. The remaining central Birmingham white strip is not solved by
  these five available HUCs. Next target is the missing Cahaba-side HUC, likely
  `031502`, once the ORNL bulk download lands it.
