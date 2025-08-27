# 2025-08-26: Elevation Tile Debugging Investigation
**Status**: Completed  
**Duration**: ~4 hours
**Context**: Investigation of missing elevation data tiles causing "green square island" visual artifacts on flood map

## Problem
User reported visual gaps in flood map elevation rendering appearing as light blue rectangular areas where green elevation tiles should display. Initially appeared to be missing SRTM elevation data files, but investigation revealed multiple layers of issues.

## Solution

### Phase 1: Initial Misdiagnosis - Missing File Approach
- **Attempted systematic SRTM download** for 373 "missing" tiles identified by audit script
- **Fixed NASA Earthdata authentication** using proper cookie-based approach vs broken redirect loops
- **Downloaded n27w081 tile** for specific problem coordinate (27.4970°, -80.4766°) 
- **Result**: Only 2 out of 373 tiles had real download issues; rest were ocean false positives

### Phase 2: Root Cause Discovery - Hidden Fallback Bug  
- **Discovered elevation API fallback** in `risk.py` that masked missing data:
  ```python
  # BAD: Hides missing data with fake approximation
  elevation = max(0.0, (abs(lat - 25.0) * 2.0) + (abs(lon + 80.0) * 0.5))
  ```
- **Removed fallback approximation** - API now returns 404 for genuinely missing data
- **Realized audit approach was fundamentally flawed** - mixed real coastal gaps with ocean false positives

### Phase 3: Alternative Technical Solution Analysis
- **Reviewed another agent's boundary/rounding fix approach**:
  - Fixed seam tolerance in `elevation_loader.py` overlap detection
  - Corrected negative coordinate rounding (`int()` → `math.floor()`)
  - Created vector-aware missing tile inventory tool
- **Assessment**: More targeted than file download approach, addresses rendering bugs vs data gaps

## Results  
- **Removed elevation fallback bug** that was hiding missing data problems
- **Fixed specific missing tile**: n27w081_1arc_v3.tif successfully downloaded and installed
- **Identified systematic audit limitations** - bbox approach generates ocean false positives
- **Documented alternative boundary fix solution** for user to deploy
- **Added warnings to audit scripts** about ocean false positive issues

## References
- [[Notes/2025/Notes 25-08#2025-08-26]] - User's daily work context
- **NASA Earthdata Authentication**: Fixed cookie-based auth for LP DAAC access
- **Bug Report Created**: Comprehensive technical summary for new developer handoff
- **Alternative Solution**: Another agent's boundary/rounding fixes in `elevation_loader.py`

#elevation #SRTM #debugging #authentication #fallback-bugs #audit-limitations