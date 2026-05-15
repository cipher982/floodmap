# Gate 10 Sensitivity: all_touched Rasterization

Both runs use the same ORNL HAND COG, FEMA NFHL SFHA features, 5m requested
FEMA geometry simplification, and ORNL elevation raster as the low-elevation
baseline.

## Results

| Threshold | all_touched | IoU | Precision | Recall | Random lift | Low-elevation lift |
|---:|---|---:|---:|---:|---:|---:|
| 1 ft | true | 0.320 | 0.612 | 0.402 | 6.305x | 2.219x |
| 1 ft | false | 0.333 | 0.600 | 0.428 | 6.720x | 2.346x |
| 3 ft | true | 0.397 | 0.599 | 0.540 | 6.172x | 2.488x |
| 3 ft | false | 0.402 | 0.579 | 0.568 | 6.492x | 2.601x |
| 6 ft | true | 0.439 | 0.560 | 0.671 | 5.770x | 2.594x |
| 6 ft | false | 0.432 | 0.533 | 0.695 | 5.975x | 2.681x |
| 10 ft | true | 0.443 | 0.505 | 0.785 | 5.200x | 2.410x |
| 10 ft | false | 0.425 | 0.474 | 0.802 | 5.316x | 2.457x |
| 20 ft | true | 0.372 | 0.387 | 0.904 | 3.988x | 2.063x |
| 20 ft | false | 0.347 | 0.359 | 0.911 | 4.022x | 2.081x |

## Readout

The pass call is not an `all_touched` artifact. Precision falls slightly with
strict rasterization, recall rises slightly, and the low-elevation lift remains
above `2.0x` at every threshold.
