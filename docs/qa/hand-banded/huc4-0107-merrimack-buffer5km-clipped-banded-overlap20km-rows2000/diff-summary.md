# Banded vs Monolithic HAND Diff

- Samples: `113635`.
- Abs diff p50/p95/p99/max sampled: `0.2` / `3.7` / `20.4` / `386.2` m.
- Within 1m: `79.821%`.
- Cells with >1m diff: `32709247`.
- 3ft threshold Jaccard: `0.8405`.
- >1m attribution: nodata-adjacent `366807` (1.121%), drain-adjacent `514082` (1.572%), band-edge-adjacent `660386` (2.019%), HUC-boundary/coastline-proxy `584800` (1.788%), unattributed interior `30830297` (94.256%).
- Heatmap: `docs/qa/hand-banded/huc4-0107-merrimack-buffer5km-clipped-banded-overlap20km-rows2000/diff-gt1m-sample.png`.

Interpretation: the failure is not mostly a visible band seam, coastline edge,
nodata fringe, or drain-adjacent artifact. The dominant bucket is unattributed
interior cells, which means the bounded-memory banding changed routed HAND
values deep inside otherwise ordinary terrain. This is why this implementation
should not be scaled.
