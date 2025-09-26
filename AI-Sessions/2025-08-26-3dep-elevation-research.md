# 2025-08-26: 3DEP Elevation Data Research
**Status**: Completed
**Duration**: ~2 hours
**Context**: Research proper enumeration and migration strategy for upgrading from SRTM to USGS 3DEP elevation data

## Problem
User reported missing elevation data tiles appearing as "green square islands" on flood map. Investigation revealed two separate issues:
1. Backend: 373 missing tiles in current SRTM dataset
2. Frontend: Scaling bug in `client-flood-layer.js` causing tiles to be invisible at certain zoom levels

Previous AI agent had created fake synthetic elevation data, which was cleaned up earlier in conversation.

## Solution

### Research Methodology
1. **Spatial Metadata Analysis**: Downloaded and analyzed `TileIndex_1x1Degree.shp` from USGS
2. **S3 Bucket Structure Investigation**: Explored `s3://prd-tnm/StagedProducts/Elevation/`
3. **Data Quality Comparison**: Downloaded sample files to verify resolution differences
4. **Coverage Verification**: Confirmed problem tiles exist in 3DEP dataset

### Key Technical Findings

**Current Dataset (SRTM)**:
- Resolution: 1 arc-second (~30m)
- File size: ~25MB per tile
- Coverage: 2,262 tiles with 373 missing
- Issues: Data gaps, inconsistent quality

**Target Dataset (3DEP)**:
- Resolution: 1/3 arc-second (~10m)
- File size: ~452MB per tile
- Coverage: 996 tiles (complete USA)
- Path: `s3://prd-tnm/StagedProducts/Elevation/13/TIFF/current/{tile}/USGS_13_{tile}.tif`

**Enumeration Methods Evaluated**:
1. ❌ **Coordinate Guessing**: Causes 404 errors for ocean tiles
2. ✅ **Spatial Metadata**: Uses `TileIndex_1x1Degree.shp` with encoded coordinates
3. ❌ **FESM Files**: Project-specific, not suitable for systematic enumeration

### Confirmed Available Tiles
Problem tiles verified in 3DEP dataset:
- `n27w081` (West Palm Beach E)
- `n27w082` (West Palm Beach W)
- `n28w081` (Fort Pierce E)

## Results
- Identified authoritative enumeration method using USGS spatial metadata
- Confirmed 3DEP provides 3x better resolution with complete coverage
- Established two viable paths: quick SRTM gap-filling vs complete 3DEP upgrade
- Storage impact: Current ~57GB → Target ~450GB

## References
- [[Notes/2025/Notes 25-08#2025-08-26]] - User's daily work log context
- USGS 3DEP Documentation: `s3://prd-tnm/StagedProducts/Elevation/`
- Spatial Metadata: `TileIndex_1x1Degree.shp` (996 USA tiles)
- Sample Analysis: `USGS_13_n27w081.tif` (10,812×10,812 pixels, 9.7m resolution)

#elevation #3DEP #SRTM #spatial-data #research #USGS
