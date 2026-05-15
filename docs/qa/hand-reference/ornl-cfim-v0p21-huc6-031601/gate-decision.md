# Gate 12: Birmingham ORNL HAND Reference Validation

Date: 2026-05-15

## Decision

Mixed pass.

ORNL CFIM v0.21 HAND is product-meaningful in Birmingham and clearly better
than the original absolute-elevation/sea-level framing. It renders visible
creek and valley corridors around Birmingham with streets intact, and it has
strong precision lift against a random same-coverage mask.

It does not meet the stricter pre-set bar of `>= 1.5x` precision lift against
the paired ORNL low-elevation baseline. The best low-elevation lift is about
`1.27x` at `20ft`, so the honest interpretation is:

- HAND is a useful drainage-relief layer.
- HAND should not be sold as a floodplain predictor that decisively beats simple
  lowland selection in every inland terrain.
- The product remains viable if the pitch is "height above local drainage" and
  the UI avoids probability, insurance, forecast, or official-risk claims.

## Inputs

- HUC6: `031601` / Black Warrior-Tombigbee
- ORNL source ZIP:
  `/mnt/storage/floodmap/data/hand-precomputed/ornl-cfim-v0.21/source-zips/031601.zip`
- Source ZIP size: `19,409,281,548` bytes
- Source ZIP SHA-256:
  `2e597ff6119a0fa022c446b40270f81df58a33a1394c6cfb5a530059ca456536`
- Converted COG:
  `/mnt/storage/floodmap/data/terrain/hand-precomputed/ornl-cfim-v0.21/031601/031601hand-u16dm.cog.tif`
- Converted COG size: `478,064,537` bytes
- Terrain manifest:
  `/mnt/storage/floodmap/data/terrain/manifests/ornl-cfim-v0p21-031601.json`
- Low-elevation baseline:
  `/mnt/storage/floodmap/data/hand-precomputed/ornl-cfim-v0.21/031601/031601-elevation.tif`
- FEMA NFHL filter: `SFHA_TF = 'T'`

## Browser QA

- Review URL:
  `http://100.125.140.78:18000/?lat=33.5186&lng=-86.8104&zoom=12&view=hand&water=3.0`
- Screenshot:
  `docs/qa/hand-precomputed/ornl-cfim-v0p21-huc6-031601/birmingham-cube-review.png`
- Result: `window.floodMap` loaded in `hand` mode at zoom `12`.
- Result: MapLibre canvas rendered and streets were visible.
- Result: HAND z12 tile returned `200` and `131072` bytes.
- Downtown Birmingham sample:
  `18.1m` / `59.4ft` above local drainage.
- Browser console: one non-blocking COOP warning from HTTP on Tailscale.

## Metrics

All-touched FEMA rasterization fetched `12,245` features and skipped `4`
empty/invalid geometries. FEMA-in-HAND-nodata was `43.69%`, below the `60%`
caveat threshold.

| Threshold | IoU | Precision | Recall | Lift vs random | Lift vs low elevation |
|---:|---:|---:|---:|---:|---:|
| 1 ft | 0.134 | 0.654 | 0.145 | 4.028x | 0.780x |
| 3 ft | 0.230 | 0.629 | 0.266 | 3.877x | 0.923x |
| 6 ft | 0.343 | 0.605 | 0.443 | 3.727x | 1.103x |
| 10 ft | 0.429 | 0.566 | 0.640 | 3.488x | 1.238x |
| 20 ft | 0.435 | 0.458 | 0.896 | 2.820x | 1.266x |

Strict rasterization did not reverse the result:

- 10 ft precision/recall: `0.551` / `0.647`
- 10 ft lift vs low elevation: `1.226x`
- 20 ft precision/recall: `0.442` / `0.902`
- 20 ft lift vs low elevation: `1.253x`

## Product Read

The strongest threshold for explanation is probably `10ft`: it captures broad
drainage corridors while keeping precision above `0.55`. `20ft` captures most
FEMA SFHA cells but becomes a broader valley-bottom layer.

The public pitch should be:

> Explore land height above local drainage.

Avoid:

- flood probability
- official FEMA equivalence
- insurance risk
- real-time storm risk
- storm sewer capacity
- "this property will flood"

## Next Call

Proceed with the national HAND serving architecture, but keep the product
language disciplined. The next engineering gate should be national source
inventory and batch conversion economics, not more hydrology model invention.
