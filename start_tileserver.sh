#!/bin/bash
# Local tile server for development with robust container management

set -e  # Exit on any error

# Function to cleanup on exit
cleanup() {
    echo "🧹 Cleaning up tileserver container..."
    docker stop tileserver-local 2>/dev/null || true
    docker rm tileserver-local 2>/dev/null || true
}

# Set trap to cleanup on script exit/interrupt
trap cleanup EXIT INT TERM

# Stop and remove any existing container with the same name
echo "🔍 Checking for existing tileserver container..."
if docker ps -a --format '{{.Names}}' | grep -q "^tileserver-local$"; then
    echo "🛑 Stopping existing tileserver container..."
    docker stop tileserver-local 2>/dev/null || true
    docker rm tileserver-local 2>/dev/null || true
fi

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