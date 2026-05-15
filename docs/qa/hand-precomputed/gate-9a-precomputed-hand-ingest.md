# Gate 9A: Precomputed HAND Ingest Spike

Date: 2026-05-15

## Verdict

ORNL/CFIM v0.21 is the best conceptual base layer, but it is not directly
downloadable from the public CFIM URL today. The public `cfim.ornl.gov` direct
HUC6 ZIP path redirects to ORNL maintenance HTML instead of a ZIP.

The older TACC/NFIE v0.1 HAND archive is downloadable without credentials and
is usable as an ingest fallback/prototype source. It has the expected final
HUC6 HAND rasters, but those rasters are float32 GeoTIFFs and must be converted
to Floodmap's `uint16-decimeters` COG format before adding them to a terrain
manifest.

NOAA/OWP FIM data is not an immediate no-credential fallback. The public docs
point to `s3://noaa-nws-owp-fim/hand_fim/`, but anonymous listing fails because
the bucket is requester-pays/authenticated; no local `esip` AWS profile exists.

## Access Checks

### ORNL CFIM

- Metadata source: `https://www.osti.gov/biblio/1630903`
- Public CFIM data URL: `https://cfim.ornl.gov/data/`
- Expected v0.21 direct pattern:
  `https://cfim.ornl.gov/data/HAND/20200601/{huc6code}.zip`
- Tested:
  `https://cfim.ornl.gov/data/HAND/20200601/010700.zip`
- Result: redirects to ORNL maintenance page, not a ZIP.
- License/disclaimer from OSTI: CC BY 4.0 with ORNL maps/data disclaimer;
  preliminary research/review product, not for emergency/life-safety decisions.

### TACC / NFIE / HydroShare

- Repository: `https://web.corral.tacc.utexas.edu/nfiedata/`
- HydroShare latest metadata:
  `https://www.hydroshare.org/resource/73aaa3efcda2465ba6227f535400f36b/`
- Dataset: 10m HAND v0.1 for 331 CONUS HUC6 units, excluding Great Lakes.
- Direct HAND pattern:
  `https://web.corral.tacc.utexas.edu/nfiedata/HAND/{huc6code}/{huc6code}hand.tif`
- License/disclaimer: CC BY 4.0 with UT maps/data disclaimer; preliminary
  research/review product, not for emergency/life-safety decisions.
- HUC6 directory listing for Merrimack `010700` is public and includes TauDEM
  intermediates plus final `010700hand.tif`.

### NOAA / OWP FIM

- Repository/docs: `https://github.com/NOAA-OWP/inundation-mapping`
- Bucket noted by docs: `s3://noaa-nws-owp-fim/hand_fim/`
- Tested anonymous listing:
  `aws s3 ls s3://noaa-nws-owp-fim/hand_fim/ --no-sign-request --region us-east-1`
- Result: `AccessDenied`; anonymous users cannot access requester-pays bucket.
- Tested local profile: `aws s3 ls ... --profile esip`
- Result: local `esip` profile is not configured.

## Sample Pulled

Pulled exactly one final HAND raster, outside git:

`/Users/davidrose/floodmap-data/hand-precomputed/tacc-v0.1/010700/010700hand.tif`

Source URL:

`https://web.corral.tacc.utexas.edu/nfiedata/HAND/010700/010700hand.tif`

Observed metadata via rasterio:

- File size: 697 MB.
- Format: BigTIFF GeoTIFF, LZW compressed.
- Shape: `14427 x 21616`, one band.
- Dtype: `float32`.
- CRS: `EPSG:4269`.
- Bounds: `(-72.14260444325225, 42.19754121366759, -70.80674855157577, 44.199021012644266)`.
- Nodata: `-3.4028234663852886e+38`.
- Internal blocks: scanline-style `(1, 14427)`.
- Overviews: none.
- Sampled finite values look like meters: min/p50/p95/p99/max
  `0.0 / 12.85 / 84.98 / 154.00 / 356.38`.

## Convertibility

Yes, this can be converted to Floodmap's source COG manifest format, but not by
just adding the downloaded TIF to the manifest. Current terrain rendering reads
source pixels as `uint16` with nodata `65535`. The TACC raster is float32 meters
with a float nodata sentinel, so it needs an encode step:

1. Read the source raster by windows.
2. Treat finite non-negative values as HAND meters.
3. Encode meters to uint16 decimeters with nodata `65535`.
4. Write a tiled/overviewed COG.
5. Add a manifest region with `encoding: "uint16-decimeters"`, CRS `EPSG:4269`,
   the observed bbox, and the converted COG URL/path.

Concrete next script outline:

```bash
uv run --with rasterio --with numpy python - <<'PY'
from pathlib import Path
import numpy as np
import rasterio
from rasterio.shutil import copy as rio_copy

src_path = Path("/Users/davidrose/floodmap-data/hand-precomputed/tacc-v0.1/010700/010700hand.tif")
tmp_path = src_path.with_name("010700hand-u16dm.tmp.tif")
cog_path = src_path.with_name("010700hand-u16dm.cog.tif")
nodata = np.uint16(65535)

with rasterio.open(src_path) as src:
    src_nodata = src.nodata
    profile = src.profile.copy()
    profile.update(
        driver="GTiff",
        dtype="uint16",
        nodata=int(nodata),
        tiled=True,
        blockxsize=512,
        blockysize=512,
        compress="DEFLATE",
        predictor=2,
        BIGTIFF="IF_SAFER",
    )
    with rasterio.open(tmp_path, "w", **profile) as dst:
        for _, window in src.block_windows(1):
            arr = src.read(1, window=window, masked=False).astype("float32")
            out = np.full(arr.shape, nodata, dtype="uint16")
            valid = np.isfinite(arr) & (arr >= 0)
            if src_nodata is not None:
                valid &= arr != src_nodata
            out[valid] = np.clip(np.rint(arr[valid] * 10), 0, int(nodata) - 1).astype("uint16")
            dst.write(out, 1, window=window)

rio_copy(
    tmp_path,
    cog_path,
    driver="COG",
    compress="DEFLATE",
    predictor=2,
    overview_resampling="nearest",
    BIGTIFF="IF_SAFER",
)
print(cog_path)
PY
```

After conversion, create a scratch manifest entry like:

```json
{
  "id": "tacc-v0p1-huc6-010700",
  "bbox": [-72.14260444325225, 42.19754121366759, -70.80674855157577, 44.199021012644266],
  "crs": "EPSG:4269",
  "url": "/Users/davidrose/floodmap-data/hand-precomputed/tacc-v0.1/010700/010700hand-u16dm.cog.tif"
}
```

## Recommendation

Use TACC v0.1 as the immediate ingest prototype because it is public and
downloadable now. Keep ORNL/CFIM v0.21 as the preferred production target if its
Globus/OLCF or public direct downloads can be restored, because its metadata
claims improved NHD HR etching and fixed boundary voids.

Next action: convert the downloaded TACC Merrimack raster to a uint16-decimeter
COG and run one local terrain v2 dynamic tile/sample smoke against a scratch
manifest. If that works, compare one or two threshold masks against the existing
Gate 6 Merrimack reference to understand how far TACC v0.1 differs from the
self-built pyflwdir baseline.
