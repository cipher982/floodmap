#!/bin/bash

# Parallel transfer using multiple rsync processes
# For maximum speed on high-bandwidth connections

SOURCE_DIR="/Users/davidrose/git/floodmap/output/elevation"
DEST_HOST="clifford"
DEST_DIR="/mnt/backup/floodmap/elevation"

# Number of parallel transfers (adjust based on your connection)
PARALLEL_JOBS=8

# Create destination directory
ssh $DEST_HOST "mkdir -p $DEST_DIR"

# Find all subdirectories and transfer them in parallel
cd "$SOURCE_DIR"
find . -maxdepth 1 -mindepth 1 -type d | \
  xargs -n1 -P$PARALLEL_JOBS -I{} \
  rsync -az \
    --partial \
    --inplace \
    --no-perms \
    --no-owner \
    --no-group \
    --compress-level=1 \
    --exclude='.DS_Store' \
    --exclude='._*' \
    -e "ssh -T -c aes128-gcm@openssh.com -o Compression=no -x" \
    {} "$DEST_HOST:$DEST_DIR/"

# Transfer any remaining files in the root directory
rsync -az \
  --partial \
  --inplace \
  --no-perms \
  --no-owner \
  --no-group \
  --compress-level=1 \
  --exclude='.DS_Store' \
  --exclude='._*' \
  --max-depth=0 \
  -e "ssh -T -c aes128-gcm@openssh.com -o Compression=no -x" \
  ./*.* "$DEST_HOST:$DEST_DIR/" 2>/dev/null || true