# HAND Sensitivity: houston-bayou-pilot

- Bbox: `(-95.82, 29.45, -94.95, 30.15)`
- Burn depths: `[0.0, 2.0, 5.0]` meters
- Accumulation thresholds: `[0.25, 1.0, 4.0, 16.0]` km^2
- FEMA comparison: `SFHA_TF = 'T'`
- Baseline variant: `5m/1km2`

## 6ft FEMA Comparison

| Variant | Burn m | Acc km2 | Drain % | 3ft coverage | 6ft coverage | 6ft IoU | 6ft Precision | 6ft Recall | 6ft Lift | 6ft Jaccard vs baseline | Wall s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `burn5m-acc16km2` | 5.000 | 16.000 | 0.56% | 10.27% | 18.54% | 0.259 | 0.486 | 0.357 | 1.927x | 0.331 | 126.8 |
| `burn2m-acc16km2` | 2.000 | 16.000 | 0.59% | 10.44% | 18.86% | 0.250 | 0.466 | 0.351 | 1.858x | 0.324 | 123.6 |
| `burn0m-acc16km2` | 0.000 | 16.000 | 0.65% | 10.22% | 18.65% | 0.248 | 0.467 | 0.346 | 1.853x | 0.305 | 123.7 |
| `burn5m-acc4km2` | 5.000 | 4.000 | 0.68% | 15.93% | 28.78% | 0.260 | 0.387 | 0.443 | 1.540x | 0.516 | 126.1 |
| `burn2m-acc4km2` | 2.000 | 4.000 | 0.73% | 16.05% | 29.05% | 0.253 | 0.375 | 0.436 | 1.502x | 0.502 | 124.1 |
| `burn0m-acc4km2` | 0.000 | 4.000 | 0.82% | 16.40% | 29.79% | 0.253 | 0.372 | 0.441 | 1.481x | 0.492 | 123.6 |
| `burn5m-acc1km2` | 5.000 | 1.000 | 1.09% | 31.72% | 52.07% | 0.235 | 0.282 | 0.585 | 1.124x | 1.000 | 124.2 |
| `burn2m-acc1km2` | 2.000 | 1.000 | 1.14% | 31.65% | 52.19% | 0.229 | 0.276 | 0.576 | 1.104x | 0.968 | 124.3 |
| `burn0m-acc1km2` | 0.000 | 1.000 | 1.26% | 32.30% | 52.74% | 0.228 | 0.274 | 0.578 | 1.095x | 0.923 | 122.7 |
| `burn5m-acc0p25km2` | 5.000 | 0.250 | 1.97% | 53.59% | 72.93% | 0.225 | 0.247 | 0.717 | 0.983x | 0.677 | 126.6 |
| `burn2m-acc0p25km2` | 2.000 | 0.250 | 2.01% | 53.39% | 72.90% | 0.220 | 0.242 | 0.709 | 0.972x | 0.664 | 125.0 |
| `burn0m-acc0p25km2` | 0.000 | 0.250 | 2.14% | 53.69% | 73.05% | 0.220 | 0.242 | 0.707 | 0.968x | 0.650 | 123.3 |

## Decision Signal

- Best 6ft precision lift: `1.927x` from `burn5m-acc16km2`.
- Flat-terrain target met: `no`. The target is `>=2.0x` precision lift without flagging most of the raster.
- Higher accumulation thresholds make Houston much less noisy, but they trade recall for precision.
- Decision: this parameter family improves Houston, but still does not make HAND a strong standalone flat-coastal flood discriminator.
- Product implication: use the stricter drainage threshold for display if we keep this layer, and frame it as a terrain/drainage screen rather than a national floodplain detector.

## Thresholds

Compared thresholds: `[3.0, 6.0, 10.0]` feet.
