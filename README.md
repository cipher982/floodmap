# Flood Map

Interactive flood risk mapping system for the USA.

## Quick Start

```bash
# Install dependencies
uv sync

# Start services
make start

# Access the app
open http://localhost:8000
```

## Core Pipelines

### Process Elevation Data (Terrain for flood calculations)
```bash
# Test with samples
uv run python src/process_elevation_usa.py --input /Volumes/Storage/floodmap-archive/srtm-raw --output data/processed/elevation --samples 5 --dry-run

# Full USA processing
uv run python src/process_elevation_usa.py --input /Volumes/Storage/floodmap-archive/srtm-raw --output data/processed/elevation
```

### Process Map Data (Roads, borders, cities)
```bash
# Test with reduced zoom
uv run python src/process_maps_usa.py --dry-run --maxzoom 8

# Full USA processing
uv run python src/process_maps_usa.py
```

## Project Structure

```
├── src/                       # Source code
│   ├── process_elevation_usa.py    # Elevation/terrain processing
│   ├── process_maps_usa.py         # Map tiles (roads, borders, cities)  
│   └── main.py                     # Main application
├── flood-map-v2/              # FastAPI application
├── data/                      # Data directory
│   ├── processed/             # Processed data
│   │   ├── elevation/         # Compressed elevation data
│   │   └── maps/              # Processed map tiles
│   └── raw/                   # Raw data and temporary files
├── utils/                     # Utility scripts and tools
├── tests/                     # Test suites
└── docs/                      # Documentation and archived files
```

## Development

- **Main app**: `flood-map-v2/api/` (FastAPI)
- **Frontend**: Static files in `flood-map-v2/static/`
- **Tests**: `pytest tests/`
- **Utilities**: `utils/` directory
- **Archived files**: `docs/cleanup/` and `docs/archive/`

## Data Sources

- **Elevation**: SRTM 1-arc-second data (47GB on external drive)
- **Maps**: OpenStreetMap USA extract (10.5GB on external drive)
- **External drive**: `/Volumes/Storage/floodmap-archive/`