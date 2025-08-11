#!/bin/bash

# Ultra-parallel transfer optimized for HIGH LATENCY connections
# Uses massive parallelism to saturate bandwidth despite latency

SOURCE_DIR="/Users/davidrose/git/floodmap/output/elevation"
DEST_HOST="clifford"
DEST_DIR="/mnt/backup/floodmap/elevation"

# AGGRESSIVE parallelism for high-latency connections
PARALLEL_JOBS=32  # Many parallel connections to overcome latency
RSYNC_BUFFER_SIZE="256K"  # Larger buffers for high latency

echo "Starting ultra-parallel transfer optimized for high latency..."
echo "Using $PARALLEL_JOBS parallel connections"

# Create destination directory
ssh $DEST_HOST "mkdir -p $DEST_DIR"

# Function to transfer a single file with optimizations
transfer_file() {
    local file="$1"
    rsync -az \
        --partial \
        --inplace \
        --no-perms \
        --no-owner \
        --no-group \
        --no-times \
        --compress-level=0 \
        --protocol=30 \
        --sockopts=SO_SNDBUF=$RSYNC_BUFFER_SIZE,SO_RCVBUF=$RSYNC_BUFFER_SIZE \
        -e "ssh -T -c aes128-gcm@openssh.com -o Compression=no -o ControlMaster=no -x" \
        "$file" \
        "$DEST_HOST:$DEST_DIR/${file#$SOURCE_DIR/}" 2>/dev/null
}

export -f transfer_file
export SOURCE_DIR DEST_HOST DEST_DIR RSYNC_BUFFER_SIZE

# Find all files and transfer them in parallel
cd "$SOURCE_DIR"
find . -type f \
    ! -name '.DS_Store' \
    ! -name '._*' \
    -print0 | \
    xargs -0 -n1 -P$PARALLEL_JOBS -I{} bash -c 'transfer_file "$@"' _ {}

echo "Transfer complete!"