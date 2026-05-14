# Boundary HAND Gate: 0106 / 0107

- Automated result: **FAIL**.
- Seam result: **PASS**.
- Region compute budget: **FAIL** for memory; **PASS** for wall time and COG size.
- Buffer: `5.0 km`.
- Shared boundary length: `371539.83 m`.
- Boundary samples: `45900`; valid paired samples: `45867`.
- Either-side <=3ft samples: `0.466%`.
- Abs diff p50/p95/max: `0.5` / `62.97` / `518.7` m.
- Visual review: **PASS with caveat**. The clipped previews do not show a
  continuous low-HAND line along the shared HUC boundary. Coastal/offshore mask
  artifacts remain a separate water/geometry cleanup issue.

## Region Runs

| HUC4 | Name | Wall s | Peak RSS MB | COG | Valid % | 3ft % |
|---|---|---:|---:|---:|---:|---:|
| `0106` | Saco | 1232.47 | 37530.5 | 168.8 MB | 51.6 | 14.38 |
| `0107` | Merrimack | 1636.2 | 38321.0 | 201.3 MB | 45.62 | 8.68 |

## Interpretation

- This gate checks whether buffered, polygon-clipped region outputs avoid synthetic low-HAND seams along the shared HUC boundary.
- The percentage of <=3ft boundary samples is the main automated seam flag; visual preview review is still required before CONUS batching.
- A seam pass with a memory fail means the boundary method is directionally sound, but the in-memory per-HUC implementation is not the CONUS builder.
