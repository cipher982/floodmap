#!/bin/bash

# Fast rsync transfer for elevation data
# Optimized for speed over fast connections

SOURCE_DIR="/Users/davidrose/git/floodmap/output/elevation/"
DEST_HOST="clifford"
DEST_DIR="/mnt/backup/floodmap/elevation/"

# Create destination directory if needed
ssh $DEST_HOST "mkdir -p $DEST_DIR"

# Rsync with maximum speed optimizations
rsync -avz \
  --progress \
  --partial \
  --inplace \
  --no-perms \
  --no-owner \
  --no-group \
  --no-times \
  --compress-level=1 \
  --skip-compress=tif/tiff/geotiff/img/jp2 \
  --exclude='.DS_Store' \
  --exclude='._*' \
  --bwlimit=0 \
  -e "ssh -T -c aes128-gcm@openssh.com -o Compression=no -x" \
  "$SOURCE_DIR" \
  "$DEST_HOST:$DEST_DIR"