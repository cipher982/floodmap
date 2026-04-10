# Phase 7 Notes

This is the valid post-fix profiling run for Phase 7 (`16487dc`).

The earlier `20260410-164805` run was captured before the vector URL-template
fix landed in production, so it reflected encoded `%7Bz%7D` placeholder traffic
and was discarded.

Representative low-zoom tile sample:

- tile: `/api/v1/tiles/vector/usa/8/69/106.pbf`
- live response header: `X-Vector-Profile: low-zoom-filtered`
- live payload: `27445` bytes with only `transportation`, `water`, and
  `waterway`
- raw MBTiles payload for the same source tile: `206873` bytes gzipped
- filtered payload for the same tile: `19670` bytes gzipped
- reduction: `90.5%`

The HAR summary in this folder is the valid post-fix network snapshot for the
phase. Use this folder, not the discarded `20260410-164805` run, for any later
comparison or write-up.
