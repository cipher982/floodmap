# Rasterization Sensitivity

This compares FEMA NFHL rasterization with `all_touched=true` against
strict center-point rasterization on the same HAND grid.

## Coverage

- All touched: FEMA cells 130,134,033; FEMA in HAND nodata 56,861,127 (43.69%)
- Strict: FEMA cells 124,753,511; FEMA in HAND nodata 54,324,122 (43.55%)

## Thresholds

| Threshold | All touched precision | Strict precision | All touched recall | Strict recall | All touched low-elev lift | Strict low-elev lift |
|---:|---:|---:|---:|---:|---:|---:|
| 1 ft | 0.654 | 0.645 | 0.145 | 0.149 | 0.780 | 0.776 |
| 3 ft | 0.629 | 0.618 | 0.266 | 0.272 | 0.923 | 0.918 |
| 6 ft | 0.605 | 0.591 | 0.443 | 0.450 | 1.103 | 1.095 |
| 10 ft | 0.566 | 0.551 | 0.640 | 0.647 | 1.238 | 1.226 |
| 20 ft | 0.458 | 0.442 | 0.896 | 0.902 | 1.266 | 1.253 |
