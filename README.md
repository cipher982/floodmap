# FloodMap 🗺️🌊

FloodMap is **an end-to-end, high-performance flood-risk mapping platform** covering the entire United States.  
It combines a FastAPI micro-service, an optimized elevation–processing pipeline and a zero-dependency HTML/JS viewer to deliver near-real-time flood visualisations down to 256 × 256 px map tiles.

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

### Tiles

Endpoint                                   | Description
------------------------------------------ | ---------------------------------------------
`/tiles/{water}/{z}/{x}/{y}.png`           | Flood-level tile (water level in **metres**)
`/tiles/topographical/{z}/{x}/{y}.png`     | Absolute-elevation colour map

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

