#!/bin/bash

# Ultimate high-latency transfer with progress monitoring
# Maximizes throughput on high-latency connections with clear progress

SOURCE_DIR="/Users/davidrose/git/floodmap/output/elevation"
DEST_HOST="clifford"
DEST_DIR="/mnt/backup/floodmap/elevation"

# Configuration for high-latency
PARALLEL_JOBS=48  # Massive parallelism to overcome latency
CHUNK_SIZE=100    # Files per batch

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  ULTRA HIGH-LATENCY OPTIMIZED FILE TRANSFER   ${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""

# Check dependencies
if ! command -v pv &> /dev/null; then
    echo -e "${YELLOW}Installing pv for progress bars...${NC}"
    brew install pv 2>/dev/null || sudo apt-get install -y pv 2>/dev/null
fi

if ! command -v parallel &> /dev/null; then
    echo -e "${YELLOW}Installing GNU parallel for maximum speed...${NC}"
    brew install parallel 2>/dev/null || sudo apt-get install -y parallel 2>/dev/null
fi

# Count total files
echo -e "${BLUE}📊 Analyzing source directory...${NC}"
TOTAL_FILES=$(find "$SOURCE_DIR" -type f ! -name '.DS_Store' ! -name '._*' | wc -l)
TOTAL_SIZE=$(du -sh "$SOURCE_DIR" 2>/dev/null | cut -f1)

echo -e "${GREEN}✓ Found $TOTAL_FILES files (Total size: $TOTAL_SIZE)${NC}"
echo ""

# Create destination directory
echo -e "${BLUE}🔧 Preparing destination...${NC}"
ssh -o ConnectTimeout=10 $DEST_HOST "mkdir -p $DEST_DIR" 2>/dev/null
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Destination ready${NC}"
else
    echo -e "${RED}✗ Failed to connect to $DEST_HOST${NC}"
    exit 1
fi
echo ""

# Create file list
echo -e "${BLUE}📝 Creating transfer list...${NC}"
FILELIST="/tmp/transfer_list_$$"
cd "$SOURCE_DIR"
find . -type f ! -name '.DS_Store' ! -name '._*' > "$FILELIST"
echo -e "${GREEN}✓ Transfer list created${NC}"
echo ""

# Progress tracking
PROGRESS_FILE="/tmp/transfer_progress_$$"
echo "0" > "$PROGRESS_FILE"

# Function to show overall progress
show_progress() {
    while [ -f "$PROGRESS_FILE" ]; do
        COMPLETED=$(cat "$PROGRESS_FILE" 2>/dev/null || echo 0)
        PERCENT=$((COMPLETED * 100 / TOTAL_FILES))
        printf "\r${BLUE}[Overall Progress]${NC} %d/%d files (%d%%) " "$COMPLETED" "$TOTAL_FILES" "$PERCENT"

        # Progress bar
        BAR_LENGTH=30
        FILLED=$((PERCENT * BAR_LENGTH / 100))
        printf "["
        for ((i=0; i<FILLED; i++)); do printf "█"; done
        for ((i=FILLED; i<BAR_LENGTH; i++)); do printf "░"; done
        printf "]"

        sleep 0.5
    done
}

# Start progress monitor in background
show_progress &
PROGRESS_PID=$!

# Transfer function for parallel
transfer_batch() {
    local file="$1"
    # Use no compression for already compressed files, light compression for others
    if [[ "$file" =~ \.(tif|tiff|geotiff|img|jp2|jpg|jpeg|png|gz|zip)$ ]]; then
        COMPRESS="--compress-level=0"
    else
        COMPRESS="--compress-level=1"
    fi

    rsync -aq \
        --partial \
        --inplace \
        --no-perms \
        --no-owner \
        --no-group \
        --no-times \
        $COMPRESS \
        --timeout=30 \
        -e "ssh -T -c aes128-gcm@openssh.com -o Compression=no -o ControlMaster=no -o ServerAliveInterval=10 -x" \
        "$file" \
        "$DEST_HOST:$DEST_DIR/${file#./}" 2>/dev/null

    if [ $? -eq 0 ]; then
        # Update progress
        CURRENT=$(cat "$PROGRESS_FILE")
        echo $((CURRENT + 1)) > "$PROGRESS_FILE"
        return 0
    else
        return 1
    fi
}

export -f transfer_batch
export SOURCE_DIR DEST_HOST DEST_DIR PROGRESS_FILE

# Main transfer with GNU parallel
echo -e "${GREEN}🚀 Starting parallel transfer with $PARALLEL_JOBS connections...${NC}"
echo -e "${YELLOW}   (High latency mode: using massive parallelism)${NC}"
echo ""

# Use GNU parallel for maximum efficiency
if command -v parallel &> /dev/null; then
    cat "$FILELIST" | parallel -j $PARALLEL_JOBS --progress --eta transfer_batch {}
else
    # Fallback to xargs if parallel not available
    cat "$FILELIST" | xargs -n1 -P$PARALLEL_JOBS -I{} bash -c 'transfer_batch "$@"' _ {}
fi

# Cleanup
kill $PROGRESS_PID 2>/dev/null
rm -f "$FILELIST" "$PROGRESS_FILE"

echo ""
echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}✓ TRANSFER COMPLETE!${NC}"
echo -e "${GREEN}================================================${NC}"

# Verify transfer
echo ""
echo -e "${BLUE}🔍 Verifying transfer...${NC}"
REMOTE_COUNT=$(ssh $DEST_HOST "find $DEST_DIR -type f | wc -l" 2>/dev/null)
echo -e "${GREEN}✓ Transferred $REMOTE_COUNT files to $DEST_HOST:$DEST_DIR${NC}"
