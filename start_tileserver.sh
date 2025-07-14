#!/bin/bash
# Local tile server for development

# Check if MBTiles file exists
if [ ! -f "map_data/tampa.mbtiles" ]; then
    echo "❌ Tampa MBTiles not found. Please run the Planetiler command first."
    exit 1
fi

echo "🚀 Starting local tile server..."
docker run --rm --name tileserver-local \
    -p 8080:8080 \
    -v $PWD/map_data:/data \
    maptiler/tileserver-gl tampa.mbtiles