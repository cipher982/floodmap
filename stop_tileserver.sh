#!/bin/bash
# Stop the local tile server

echo "🛑 Stopping tileserver..."

# Stop the container gracefully
if docker ps --format '{{.Names}}' | grep -q "^tileserver-local$"; then
    echo "📦 Stopping tileserver-local container..."
    docker stop tileserver-local
    echo "✅ Tileserver stopped successfully"
else
    echo "ℹ️  No tileserver-local container running"
fi

# Clean up any leftover containers
if docker ps -a --format '{{.Names}}' | grep -q "^tileserver-local$"; then
    echo "🧹 Removing tileserver-local container..."
    docker rm tileserver-local
fi

echo "✅ Tileserver cleanup complete"