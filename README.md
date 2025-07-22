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
uv run python process_elevation_usa.py --input /Volumes/Storage/floodmap-archive/srtm-raw --output compressed_data/test --samples 5 --dry-run

# Full USA processing
uv run python process_elevation_usa.py --input /Volumes/Storage/floodmap-archive/srtm-raw --output compressed_data/usa
```

### Process Map Data (Roads, borders, cities)
```bash
# Test with reduced zoom
uv run python process_maps_usa.py --dry-run --maxzoom 8

# Full USA processing
uv run python process_maps_usa.py
```

## Project Structure

```
├── process_elevation_usa.py    # Elevation/terrain processing
├── process_maps_usa.py         # Map tiles (roads, borders, cities)
├── flood-map-v2/              # Main application
├── compressed_data/           # Processed elevation data
├── map_data/                  # Processed map tiles
├── scripts/                   # Utility scripts
├── tests/                     # Test suites
└── cleanup/                   # Archived files
```

## Development

- **Main app**: `flood-map-v2/api/` (FastAPI)
- **Frontend**: Static files in `flood-map-v2/static/`
- **Tests**: `pytest tests/`
- **Archived files**: `cleanup/` and `archive/`

## Data Sources

- **Elevation**: SRTM 1-arc-second data (47GB on external drive)
- **Maps**: OpenStreetMap USA extract (10.5GB on external drive)
- **External drive**: `/Volumes/Storage/floodmap-archive/`