#!/bin/bash

# Fast transfer for the mbtiles file using split and parallel transfers

SOURCE_FILE="output/usa-complete.mbtiles"
CONFIG_FILE="output/config.json"
DEST_HOST="clifford"
DEST_DIR="/mnt/backup/floodmap"

echo "Transferring config.json..."
rsync -av "$CONFIG_FILE" "$DEST_HOST:$DEST_DIR/"

echo "Splitting and transferring mbtiles file with parallel chunks..."

# Split the file into 100MB chunks and transfer in parallel
CHUNK_SIZE="100M"
TEMP_DIR="/tmp/mbtiles_chunks_$$"
mkdir -p "$TEMP_DIR"

echo "Splitting file into chunks..."
split -b $CHUNK_SIZE "$SOURCE_FILE" "$TEMP_DIR/chunk_"

echo "Transferring chunks in parallel..."
ls "$TEMP_DIR"/chunk_* | \
  xargs -n1 -P16 -I{} \
  rsync -aq \
    --partial \
    --inplace \
    -e "ssh -T -c aes128-gcm@openssh.com -o Compression=no -x" \
    {} "$DEST_HOST:$DEST_DIR/mbtiles_chunks/"

echo "Reassembling on remote..."
ssh "$DEST_HOST" "cd $DEST_DIR && cat mbtiles_chunks/chunk_* > usa-complete.mbtiles && rm -rf mbtiles_chunks"

# Cleanup
rm -rf "$TEMP_DIR"

echo "Transfer complete!"
echo ""
echo "Update your production .env to use:"
echo "MAP_DATA_PATH=/mnt/backup/floodmap"
