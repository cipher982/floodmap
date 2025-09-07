# FloodMap 🗺️🌊

FloodMap is **an end-to-end, high-performance flood-risk mapping platform** covering the entire United States.  
It combines a FastAPI micro-service, an optimized elevation–processing pipeline and a zero-dependency HTML/JS viewer to deliver near-real-time flood visualisations down to 256 × 256 px map tiles.


[floodmap.drose.io](https://floodmap.drose.io)

---

## ✨ Key Capabilities

- **Nation-wide coverage** – SRTM 1-arc-second DEM is tiled, compressed (Zstandard) and cached for millisecond look-ups.
- **Water-level visualisation** – Generate colour-mapped PNG tiles for *any* requested water-level between **–10 m** and **+1 000 m** (configurable).
- **Topographical mode** – Switch to an absolute-elevation colour scale for terrain inspection.
- **Vector overlays** – Optional road / city / boundary tiles are served from MBTiles (OpenStreetMap extract).
- **Predictive pre-loading & persistent caches** greatly reduce cold-start latency.
- **Observability built-in** – Prometheus metrics, structured logging and configurable OTLP traces.

<p align="center"><img src="docs/figures/demo.gif" width="700" alt="Demo animation"></p>

---

## 🏗️ Project Layout

```
├── src/                      # Python source code
│   ├── api/                  # FastAPI application (floodmap.api)
│   │   ├── routers/          # Versioned HTTP endpoints
│   │   ├── services/         # (future) business logic helpers
│   │   ├── middleware/       # ASGI middleware (rate-limiter, tracing…)
│   │   ├── color_mapping.py  # NumPy-vectorised colour LUTs
│   │   ├── elevation_loader.py  # Thread-safe on-demand DEM loader
│   │   ├── tile_cache.py         # LRU in-memory PNG cache
│   │   └── …
│   ├── process_elevation_usa.py  # One-off DEM compression pipeline
│   ├── process_maps_usa.py       # Vector MBTiles generation helper
│   └── web/                  # Lightweight static front-end
│
├── tests/                    # Pytest suite (unit + integration)
├── utils/                    # Misc. notebooks & ad-hoc scripts
├── docs/                     # Additional background docs & figures
└── Dockerfile                # Production image (multi-stage)
```

---

## ⚡ Quick-start (macOS / Linux)

```bash
# 1. Clone & install deps (uses uv – https://github.com/astral-sh/uv)
uv sync


# 2. Start everything
make start   # == docker-compose up ‑d tileserver && uvicorn src.api.main:app --reload

# 3. Open the viewer
open http://localhost:8000   # or your preferred browser
```

The default Makefile recipe spins up:

| Service          | Port | Description                                  |
| ---------------- | ---- | -------------------------------------------- |
| fastapi          | 8000 | JSON /tiles/* PNG endpoints & REST API       |
| static-frontend  | 8000 | Served via FastAPI `StaticFiles`             |
| tileserver-gl    | 8080 | Optional vector-tile server (Docker)         |

---

## ⚙️ Configuration

All tunables live in **`src/api/config.py`** and can be overridden via environment variables or a *.env* file.

Variable              | Purpose                                  | Default
--------------------- | ---------------------------------------- | ------------------------------
`PROJECT_ROOT`        | Absolute project path                    | repo root
`COMPRESSED_DATA_DIR` | Directory containing `*.zst` DEM tiles   | `compressed_data/`
`ELEVATION_CACHE_SIZE`| In-RAM LRU entries (tiles)               | `50`
`TILE_CACHE_SIZE`     | In-RAM LRU entries (PNG responses)       | `1000`
`MIN_WATER_LEVEL` / `MAX_WATER_LEVEL` | Allowed request range     | `-10` / `1000`

See *.env.example* for a full list.

---

## 🐳 Docker Compose

- Dev (ports published): `docker compose up -d`
- Prod (internal-only): `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`

Details:
- Dev maps to host for easy access (clickable logs). Override file publishes `${API_PORT}:8000` and `${TILESERVER_PORT}:8080`.
- Prod does not publish any host ports. The API listens on `8000` inside the compose network and the tileserver on `8080`.
- Network name defaults to `${COMPOSE_PROJECT_NAME}-network` (e.g., `floodmap-network`).

Reverse proxy:
- Run your proxy on the same Docker network and target `webapp:8000`.
- Example: `docker run -d --network floodmap-network your-proxy-image`
- Nginx upstream example: `upstream floodmap { server webapp:8000; }`

Verify prod:
- `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` (no `ports:` on webapp)
- From a container on the network: `curl http://webapp:8000/api/health`

Note: Only one Dockerfile is used. `Dockerfile.prod` has been removed to avoid confusion.

## 🏞️ Data Pipeline

### 1. Elevation (DEM) Compression

The raw US SRTM 1-arc-second GeoTIFFs are *huge* (≈45 GB).  
`process_elevation_usa.py` chunks them into 256 × 256 tiles, serialises each tile as *little-endian int16* bytes and compresses with **Zstandard (level 3)**.  
Metadata (bounds, CRS, nodata, etc.) is persisted per-tile in a side-car JSON.

```bash
uv run python src/process_elevation_usa.py \
  --input /mnt/raw_srtm/us/ \
  --output compressed_data/usa \
  --workers 8                \
  --compression-level 5
```

Results: **≈4 × space saving** and ~25–30 ms decompression per tile on a laptop.

### 2. Vector Tiles

`process_maps_usa.py` ingests the latest OpenStreetMap extract, filters layers (roads, admin boundaries, landuse, places) and writes an **MBTiles** database with tiles up to `z14`.

### 3. Precompressed Elevation Tiles (.u16.br)

Precompressed raw elevation tiles eliminate server CPU work and reduce bandwidth by sending compact **uint16** arrays to the browser. These are served by the v1 API and consumed by the client renderer.

- Endpoint: `/api/v1/tiles/elevation-data/{z}/{x}/{y}.u16?method=precompressed`
- Encoding: negotiate `br` (Brotli) or `gzip` via `Accept-Encoding`; server uses sendfile for `.u16.br/.gz`.
- Runtime fallback: if a precompressed file is missing, the API generates a runtime tile and compresses it on the fly.

#### Generate (Host / Dev)

Use the hardened generator (loud checks; no silent bad writes):

```bash
uv run python tools/generate_precompressed_elevation_tiles.py \
  --source-dir data/elevation-source \
  --output-dir data/elevation-tiles \
  --zoom-min 8 --zoom-max 11 \
  --no-gz         # only .u16.br
```

Tips:
- Add `--bbox <minLon> <minLat> <maxLon> <maxLat>` to constrain coverage (e.g., a metro).
- Add `--no-skip` to overwrite previously generated tiles.

#### Generate (In Container / Prod)

Ensure the volumes are mounted (see docker-compose.prod.yml) and the output mount is writable during generation.

```bash
docker compose run --rm webapp \
  python tools/generate_precompressed_elevation_tiles.py \
    --output-dir /app/data/elevation-tiles \
    --zoom-min 8 --zoom-max 11 \
    --no-gz --no-skip
```

#### Loud Safety Checks (What The Script Enforces)

- Validates `--source-dir` exists and has thousands of `.zst` files; otherwise aborts with a fatal message.
- Skips writing when the loader returns no data (ocean/outside coverage). These are counted as `tiles_skipped_missing` in the per‑zoom summary and manifest.
- Writes a manifest at `output_dir/manifest.json` with totals and variants.

#### Validate A Random Sample

Fetch a generated tile using precompressed mode and inspect the payload:

```bash
API=http://127.0.0.1:8000
Z=9; X=140; Y=215
curl -sS -D /tmp/h.txt -o /tmp/tile.br -H 'Accept-Encoding: br' \
  "$API/api/v1/tiles/elevation-data/$Z/$X/$Y.u16?method=precompressed"
brotli -d -f /tmp/tile.br -o /tmp/tile.dec
python3 - <<'PY'
from array import array
b=open('/tmp/tile.dec','rb').read(); a=array('H'); a.frombytes(b)
mn=min(a); mx=max(a); nod=sum(1 for v in a if v==65535); tot=len(a)
print('bytes',len(b),'min',mn,'max',mx,'nodata%',round(nod*100.0/tot,2))
PY
```

Heuristics:
- Land tiles should have nodata% near 0 and realistic min/max; precompressed `.br` typically tens of KB.
- Tiny `.br` (~14 bytes) indicates an all‑65535 tile (pure ocean is OK; large swaths of land are not). Re‑generate if unexpected.

#### Smart Coverage Validation Script

Use the helper to summarise counts/sizes and decode a random sample per zoom.

```bash
# Local file validation
python tools/validate_precompressed_tiles.py \
  --tiles-dir data/elevation-tiles \
  --zooms 8 9 10 11 \
  --samples 100

# API validation (fetches via precompressed endpoint)
python tools/validate_precompressed_tiles.py \
  --api http://127.0.0.1:8000 \
  --zooms 9 10 11 \
  --samples 50
```

Output includes per-zoom size buckets and nodata% percentiles for quick sanity.

#### Size Planning (USA Coverage)

- z0–11: ~5–6 GB total (Brotli Q10). Manageable on a laptop.
- z12 adds ~15–16 GB; z13 adds ~60+ GB; prefer regional bboxes for z12+.

---

## 🚀 Runtime Architecture

1. **HTTP request** `GET /tiles/{water}/{z}/{x}/{y}.png` arrives.
2. ASGI **rate-limiter** & **tracing** middleware run.
3. `tile_cache` is queried (key = water+z+x+y).  
   • **HIT ➜** return cached 256 × 256 PNG immediately.  
   • **MISS ➜** proceed.
4. `elevation_loader` fetches & mosaics the required DEM bytes:  
   – Persistent on-disk Zstd *Context* avoids re-allocations.  
   – A tiny `diskcache` layer keeps LRU decompressed arrays on SSD.
5. `color_mapper` converts the `int16` NumPy array ➜ RGBA via pre-computed LUTs (vectorised, no Python loop).
6. A *ThreadPoolExecutor* encodes the array to PNG (Pillow), level 1.
7. Response is cached and streamed back (~50–90 ms cold-path).

![Sequence diagram](docs/figures/sequence.png)

---

## 🔌 Public API

### v1 Tiles

Endpoint                                                   | Description
---------------------------------------------------------- | ---------------------------------------------
`/api/v1/tiles/elevation-data/{z}/{x}/{y}.u16`             | Raw uint16 elevation tile (runtime by default)
`/api/v1/tiles/elevation-data/{z}/{x}/{y}.u16?method=precompressed` | Serve precompressed `.u16.br`/`.gz` if present
`/api/v1/tiles/vector/usa/{z}/{x}/{y}.pbf`                 | Vector tiles proxy (tileserver-gl)
`/api/v1/tiles/health`                                     | Health/metadata for tile endpoints

### Risk assessment

`POST /risk/location` → JSON body `{latitude, longitude}` returns:

```jsonc
{
  "elevation_m": 2.3,
  "flood_risk_level": "high",   // very_high | high | moderate | low | estimated | unknown
  "risk_description": "High flood risk - elevation 2.3m is near flood-prone areas",
  "water_level_m": 1.0
}
```

---

## 🧪 Testing

```bash
uv run pytest -q         # fast unit tests (< 1 s each)
uv run pytest -m slow    # include integration & e2e tests (Playwright)
```

CI configuration lives in *.github/workflows/*. Pull-requests run the full matrix (unit, lint, mypy, e2e-headless).

---

## 📝 Development Tips

• **Debug helpers** – A set of `debug_*.py` scripts lives at repo root for quick profiling and visual checks.  
• **Hot reload** – `uvicorn src.api.main:app --reload` watches for changes.  
• **Data outside repo** – Large raw datasets are symlinked via `ARCHIVED_DATA → /Volumes/Storage/floodmap-archive`.
• **Gotchas** – When generating precompressed tiles on host, always pass `--source-dir data/elevation-source` and `--output-dir data/elevation-tiles`. Avoid using container‑only paths (`/app/...`) outside Docker — this will yield empty data and tiny `.br` files.

---

## 📋 Roadmap

- [ ] Switch PNG encoding to **pypng + streaming** saver to cut memory allocation.
- [ ] WebGL front-end with dynamic slider instead of full tile re-render.
- [ ] Add per-state AWS S3 public buckets for elevation data.
- [ ] Terraform module to deploy to Fargate with ALB / CloudFront CDN.

---

## 📄 License

Distributed under the **MIT License**.  
© 2024 FloodMap contributors
