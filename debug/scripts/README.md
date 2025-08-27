# Debug Scripts

These scripts were created during debugging the "green square artifact" issue.

## disable_all_caching.py
Disables all caching layers for debugging purposes. Use when you need to ensure fresh data on every request.
**WARNING**: Makes the app very slow. Restore with git checkout after use.

## fix_ocean_zeros.py  
Attempted fix that treated elevation=0 as NODATA. 
**DO NOT USE**: This is a footgun that breaks legitimate 0m elevation areas (Netherlands, New Orleans, etc).
Keep for reference of what NOT to do.

## Root Cause
The green square artifact was caused by:
1. Bad elevation data files with zeros instead of NODATA for ocean areas
2. Server encoding 0m as 3449 (0x0d79) in uint16 format
3. Client rendering 3449 as green land instead of blue ocean

## Solution
- Client-side: Enhanced NODATA handling (isAllNoData fast path, explicit OCEAN_RGBA)
- Data cleanup: Removed bad ocean tiles (n26_w077-079, n27_w078-079)
- Remaining issue: Some coastal tiles (n27_w081) still have zeros for ocean areas