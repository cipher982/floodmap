# Flood Buddy – Elevation & Flood-risk Tiles

![Architecture](docs/arch.svg)

## 1. Overview
Flood Buddy turns raw public-domain elevation data into colored map tiles and serves them through a FastAPI backend.
Key design choices:

* **Single MBTiles datastore** – tiles are stored in `elevation.mbtiles`, avoiding millions of tiny PNG files and heavy inode usage.
* **Public Open-Data ingestion** – elevation COGs are pulled anonymously from AWS (e.g. `s3://usgs-srtm`). No USGS API keys or rate-limits.
* **Docker-first runtime** – shipped as an image based on `ghcr.io/osgeo/gdal:alpine` so GDAL/Rasterio just work.
* **Observability built-in** – Prometheus metrics, health checks and distributed rate-limiting (Redis).

## 2. Quick start with Docker
```bash
# Clone and create a .env from the template
cp .env.example .env
# edit GMAP_API_KEY, REDIS_URL (optional) etc.

# Build (or pull) and run
docker build -t flood-buddy .

docker run -p 5001:5001 \
  -v $(pwd)/data:/data \
  --env-file .env \
  flood-buddy

# Visit
open http://localhost:5001/
```

The first run downloads public DEM COGs (~<1 GB for CONUS at 1-arc-second) and builds `elevation.mbtiles`. Subsequent runs start instantly.

## 3. Environment variables
| Variable | Default | Purpose |
|----------|---------|---------|
| `GMAP_API_KEY` | – | Google Maps JS API key for front-end map. |
| `INPUT_DIR` | `/data/input` | Where raw GeoTIFF/COG files are stored. |
| `PROCESSED_DIR` | `/data/processed` | Output directory for VRT, tiles & MBTiles. |
| `MBTILES_PATH` | `$PROCESSED_DIR/elevation.mbtiles` | Override MBTiles location. |
| `COLOR_RAMP` | `scripts/color_ramp.txt` | Color table for GDAL. |
| `MAX_TILES_PER_SECOND` | `30` | Per-IP rate limit (Redis-backed). |
| `REDIS_URL` | – | `redis://host:port` for distributed rate limiting. Optional. |
| `MBTILES_POOL_SIZE` | `4` | SQLite connection pool size. |
| `AWS_REGION` | `us-east-1` | Region for public S3 endpoints. |

See `.env.example` for a full template.

## 4. Endpoints
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Main HTML page with user-centric map overlay. |
| `GET` | `/tiles/{z}/{x}/{y}` | PNG tile (XYZ scheme, 8≤z≤9 by default). |
| `GET` | `/healthz` | Liveness/readiness probe. Returns JSON `{status, mbtiles, redis}`. |
| `GET` | `/metrics` | Prometheus metrics in OpenMetrics format. |

## 5. Development workflow
1. `pytest -q` – runs unit + integration tests (builds sample MBTiles in temp dir).
2. `scripts/download_aws_dem.py` – pulls COGs into `INPUT_DIR`.
3. `scripts/process_tif.py` – mosaics, tiles, and writes MBTiles.
4. `uvicorn main:app --reload` – hot-reload API during development.

## 6. Production notes
* Behind a reverse-proxy/CDN, be sure to forward `X-Real-IP` so rate-limiter sees the real client.
* Mount `/data` on fast SSD; GDAL tiling is I/O-heavy the first time.
* Scrape `/metrics` every 15 s to size Redis and tune rate limit thresholds.
