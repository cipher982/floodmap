# HAND Candidate vs Reference Diff

- Reference note: Gate 6 pyflwdir is a failed prototype reference, not ground truth; use this only as a difference smoke.
- Reference CRS / candidate CRS: `EPSG:5070` / `EPSG:4269`.
- Reprojection: `True` with `nearest` resampling.
- Samples: `132060` of target `250000`.
- Abs diff p50/p95/p99/max sampled: `1.7` / `64.205` / `176.766` / `614.8` m.
- Within 1m: `40.576%`.
- Cells with >1m diff: `98214105`.
- 3ft/6ft/10ft Jaccard: `0.5739` / `0.5997` / `0.6314`.
