#!/bin/bash

# FloodMap Elevation Data Deployment Script
# This script handles the 13GB elevation dataset deployment

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DATA_SOURCE="${PROJECT_ROOT}/output/elevation"
DATA_DEST="${ELEVATION_DATA_PATH:-/data/floodmap/elevation}"
BACKUP_DIR="${DATA_DEST}.backup.$(date +%Y%m%d_%H%M%S)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

# Check if running as root (recommended for data deployment)
check_permissions() {
    if [[ $EUID -ne 0 ]]; then
        warn "Not running as root. Make sure you have write permissions to ${DATA_DEST}"
    fi
}

# Verify source data exists and is complete
verify_source_data() {
    log "Verifying source elevation data..."
    
    if [[ ! -d "$DATA_SOURCE" ]]; then
        error "Source data directory not found: $DATA_SOURCE"
        exit 1
    fi
    
    # Count files
    zst_count=$(find "$DATA_SOURCE" -name "*.zst" | wc -l)
    json_count=$(find "$DATA_SOURCE" -name "*.json" | wc -l)
    
    log "Found $zst_count compressed elevation files and $json_count metadata files"
    
    if [[ $zst_count -eq 0 ]]; then
        error "No elevation data files found in $DATA_SOURCE"
        exit 1
    fi
    
    if [[ $zst_count -ne $json_count ]]; then
        error "Mismatch: $zst_count .zst files but $json_count .json files"
        exit 1
    fi
    
    # Check total size
    total_size=$(du -sh "$DATA_SOURCE" | cut -f1)
    log "Total data size: $total_size"
}

# Create backup of existing data
backup_existing_data() {
    if [[ -d "$DATA_DEST" ]]; then
        log "Creating backup of existing data..."
        mkdir -p "$(dirname "$BACKUP_DIR")"
        cp -r "$DATA_DEST" "$BACKUP_DIR"
        success "Backup created: $BACKUP_DIR"
    fi
}

# Sync data with verification
sync_data() {
    log "Starting data synchronization..."
    
    # Create destination directory
    mkdir -p "$DATA_DEST"
    
    # Use rsync for efficient, resumable transfer
    rsync -avh --progress --checksum \
        --exclude="*.tmp" \
        --exclude=".*" \
        "$DATA_SOURCE/" "$DATA_DEST/"
    
    success "Data synchronization completed"
}

# Verify deployment integrity
verify_deployment() {
    log "Verifying deployment integrity..."
    
    # Check file counts
    src_zst_count=$(find "$DATA_SOURCE" -name "*.zst" | wc -l)
    dest_zst_count=$(find "$DATA_DEST" -name "*.zst" | wc -l)
    
    if [[ $src_zst_count -ne $dest_zst_count ]]; then
        error "File count mismatch: source=$src_zst_count, dest=$dest_zst_count"
        exit 1
    fi
    
    # Spot check a few files with checksums
    log "Performing spot check with checksums..."
    sample_files=$(find "$DATA_SOURCE" -name "*.zst" | head -5)
    
    for src_file in $sample_files; do
        filename=$(basename "$src_file")
        dest_file="$DATA_DEST/$filename"
        
        if [[ ! -f "$dest_file" ]]; then
            error "Missing file: $dest_file"
            exit 1
        fi
        
        src_checksum=$(sha256sum "$src_file" | cut -d' ' -f1)
        dest_checksum=$(sha256sum "$dest_file" | cut -d' ' -f1)
        
        if [[ "$src_checksum" != "$dest_checksum" ]]; then
            error "Checksum mismatch for $filename"
            exit 1
        fi
    done
    
    success "Deployment verification completed"
}

# Set appropriate permissions
set_permissions() {
    log "Setting appropriate permissions..."
    
    # Make data read-only for security
    find "$DATA_DEST" -type f -exec chmod 444 {} \;
    find "$DATA_DEST" -type d -exec chmod 555 {} \;
    
    # If running as root, set ownership to a non-root user
    if [[ $EUID -eq 0 ]] && command -v id >/dev/null && id -u 1000 >/dev/null 2>&1; then
        chown -R 1000:1000 "$DATA_DEST"
    fi
    
    success "Permissions set"
}

# Cleanup old backups (keep last 3)
cleanup_old_backups() {
    local backup_parent="$(dirname "$DATA_DEST")"
    local backup_pattern="$(basename "$DATA_DEST").backup.*"
    
    # Find and remove old backups (keep last 3)
    find "$backup_parent" -maxdepth 1 -name "$backup_pattern" -type d | \
        sort -r | tail -n +4 | xargs rm -rf
    
    log "Cleaned up old backups"
}

# Main execution
main() {
    log "Starting FloodMap elevation data deployment"
    
    check_permissions
    verify_source_data
    backup_existing_data
    sync_data
    verify_deployment
    set_permissions
    cleanup_old_backups
    
    success "Elevation data deployment completed successfully!"
    success "Data location: $DATA_DEST"
    success "Data ready for docker-compose deployment"
}

# Parse command line arguments
case "${1:-}" in
    --verify-only)
        verify_source_data
        if [[ -d "$DATA_DEST" ]]; then
            verify_deployment
        fi
        ;;
    --help|-h)
        echo "FloodMap Data Deployment Script"
        echo ""
        echo "Usage: $0 [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  --verify-only    Only verify data integrity, don't deploy"
        echo "  --help, -h       Show this help message"
        echo ""
        echo "Environment Variables:"
        echo "  ELEVATION_DATA_PATH    Destination path (default: /data/floodmap/elevation)"
        ;;
    *)
        main "$@"
        ;;
esac