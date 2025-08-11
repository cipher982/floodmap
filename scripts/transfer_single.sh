#!/bin/bash

# Single connection transfer with resume capability

SOURCE_FILE="output/usa-complete.mbtiles"
CONFIG_FILE="output/config.json"
DEST_HOST="clifford"
DEST_DIR="/mnt/backup/floodmap"

echo "Using single connection with resume capability..."

# Use rsync with aggressive resume and no compression (already compressed file)
rsync -avP \
  --partial \
  --append-verify \
  --timeout=300 \
  --compress-level=0 \
  -e "ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=10 -o TCPKeepAlive=yes" \
  "$SOURCE_FILE" "$CONFIG_FILE" \
  "$DEST_HOST:$DEST_DIR/"

echo ""
echo "If transfer fails, just run this script again - it will resume!"
echo ""
echo "After completion, update production .env:"
echo "MAP_DATA_PATH=/mnt/backup/floodmap"