# Whitebox Correctness Checks

- Gate 8 correctness pass: `False`.
- p99 <= 1m: `False`.
- >=99% within 1m: `False`.
- 3ft/6ft/10ft Jaccard >=0.97: `False` / `False` / `False`.

This compares a mapped-flowline Whitebox stream raster against the pyflwdir HUC4 reference. A pass is not production acceptance until the drainage definition and DEM conditioning are comparable.
