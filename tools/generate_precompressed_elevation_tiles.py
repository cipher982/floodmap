#!/usr/bin/env python3
"""
Comprehensive pre-compression generator for elevation tiles.

Generates raw (.u16) and compressed (.u16.br, .u16.gz) tiles for a given
zoom range using the production elevation pipeline:

  - Uses elevation_loader.get_elevation_for_tile(x, y, z, tile_size=256)
  - Normalizes to uint16 exactly like the runtime endpoint
  - Writes to a web-tiles directory structure: {z}/{x}/{y}.u16[.br|.gz]

Key features
  - Resumable: skips tiles that already exist (by default)
  - Bounding box support to constrain coverage
  - Parallel generation with a process pool
  - Manifest with basic stats
  - Identical output to production runtime path

Usage examples
  # Default: detect coverage from source .zst metadata, z=8..15
  python tools/generate_precompressed_elevation_tiles.py \
    --output-dir elevation-tiles \
    --zoom-min 8 --zoom-max 12 \
    --workers 8

  # Constrain to a bbox and specific zooms
  python tools/generate_precompressed_elevation_tiles.py \
    --bbox -90 24 -80 31 \
    --zoom-min 10 --zoom-max 12 \
    --skip-existing \
    --output-dir elevation-tiles

Notes
  - Generating every tile for z=8..15 across large regions results in
    very large tile counts. Prefer running in tranches (by zoom or bbox).
  - This script intentionally mirrors tiles_v1.generate_elevation_data_sync
    to ensure byte-identical output for .u16 payloads.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional, Tuple

from dotenv import load_dotenv

# Third-party
import numpy as np

try:
    import brotli  # type: ignore
except Exception:  # pragma: no cover - optional
    brotli = None


# Ensure src/api is importable when the script is run from project root
ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / 'src', ROOT / 'src' / 'api'):
    sys.path.insert(0, str(p))

# Load environment (.env) for config
load_dotenv()

from config import ELEVATION_DATA_DIR, TILE_SIZE, NODATA_VALUE  # type: ignore
# Import both the global instance and the class so we can override the data dir when needed
from elevation_loader import elevation_loader as _default_loader, ElevationDataLoader  # type: ignore


@dataclass(frozen=True)
class Tile:
    z: int
    x: int
    y: int


def deg2num(lat_deg: float, lon_deg: float, zoom: int) -> Tuple[int, int]:
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (xtile, ytile)


def num2deg(xtile: int, ytile: int, zoom: int) -> Tuple[float, float, float, float]:
    n = 2.0 ** zoom
    lon_deg_left = xtile / n * 360.0 - 180.0
    lon_deg_right = (xtile + 1) / n * 360.0 - 180.0
    lat_deg_top = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ytile / n))))
    lat_deg_bottom = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ytile + 1) / n))))
    return (lat_deg_top, lat_deg_bottom, lon_deg_left, lon_deg_right)


def discover_coverage_bbox_from_metadata(src_dir: Path) -> Tuple[float, float, float, float]:
    """Scan .json sidecars to compute the union coverage bbox.

    Returns (min_lon, min_lat, max_lon, max_lat).
    """
    min_lon = 180.0
    max_lon = -180.0
    min_lat = 90.0
    max_lat = -90.0

    # Iterate only .json files to read bounds
    for meta in src_dir.glob("*.json"):
        try:
            data = json.loads(meta.read_text())
            b = data.get('bounds') or {}
            left = float(b.get('left'))
            right = float(b.get('right'))
            top = float(b.get('top'))
            bottom = float(b.get('bottom'))
        except Exception:
            continue

        min_lon = min(min_lon, left)
        max_lon = max(max_lon, right)
        min_lat = min(min_lat, bottom)
        max_lat = max(max_lat, top)

    if min_lon > max_lon or min_lat > max_lat:
        raise RuntimeError(f"Could not determine coverage bbox from {src_dir}")

    return (min_lon, min_lat, max_lon, max_lat)


def tiles_for_bbox(z: int, min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> Iterator[Tile]:
    # Clamp to Web Mercator limits
    min_lat_c = max(-85.05112878, min(85.05112878, min_lat))
    max_lat_c = max(-85.05112878, min(85.05112878, max_lat))
    min_lon_c = max(-180.0, min(180.0, min_lon))
    max_lon_c = max(-180.0, min(180.0, max_lon))

    x_min, y_max = deg2num(min_lat_c, min_lon_c, z)
    x_max, y_min = deg2num(max_lat_c, max_lon_c, z)

    x0, x1 = min(x_min, x_max), max(x_min, x_max)
    y0, y1 = min(y_min, y_max), max(y_min, y_max)

    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            yield Tile(z, x, y)


def normalize_to_uint16(elevation_data: np.ndarray) -> bytes:
    """Match production normalization (-500..9000m → 0..65534; 65535=NODATA)."""
    # Return empty elevation data if no array
    if elevation_data is None:
        empty = np.full((TILE_SIZE, TILE_SIZE), 65535, dtype=np.uint16)
        return empty.tobytes()

    normalized = np.zeros_like(elevation_data, dtype=np.float32)

    nodata_mask = (elevation_data == NODATA_VALUE) | (elevation_data < -500) | (elevation_data > 9000)
    valid_mask = ~nodata_mask

    normalized[valid_mask] = np.clip(
        (elevation_data[valid_mask] + 500) / 9500 * 65534,
        0,
        65534,
    )
    normalized[nodata_mask] = 65535

    return normalized.astype(np.uint16).tobytes()


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def process_tile(z: int, x: int, y: int, out_dir: Path, generate_br: bool, generate_gz: bool, write_raw: bool, loader: ElevationDataLoader, skip_existing: bool = True) -> Optional[dict]:
    """Generate and write one tile in all requested variants.

    Returns stats dict on success, or None if skipped/missing.
    """
    # Short-circuit if any final artifact exists and skipping is enabled
    base_dir = out_dir / str(z) / str(x)
    base = base_dir / f"{y}.u16"
    br_path = base.with_suffix('.u16.br')
    gz_path = base.with_suffix('.u16.gz')

    if skip_existing and (base.exists() or br_path.exists() or gz_path.exists()):
        return None

    # Extract using production loader (trust loader to decide coverage)
    try:
        arr = loader.get_elevation_for_tile(x, y, z, tile_size=TILE_SIZE)
    except Exception as e:
        # Loud failure: include tile coordinates and exception
        print(f"ERROR: loader failed for {z}/{x}/{y}: {e}")
        arr = None

    # Fallback: if no data extracted (pure ocean/outside coverage), write an all-NODATA tile.
    all_nodata = False
    if arr is None:
        # Do NOT silently write bogus tiles; skip writing, record as skipped.
        return {
            'z': z, 'x': x, 'y': y,
            'skipped_missing': True,
        }
    else:
        payload = normalize_to_uint16(arr)
        # Detect 100% NODATA outputs; often legitimate over ocean, but useful to track loudly
        from array import array as _arr
        a = _arr('H'); a.frombytes(payload)
        tot = len(a)
        nod = sum(1 for v in a if v == 65535)
        all_nodata = (nod == tot)

    ensure_dir(base_dir)

    stats = {
        'z': z, 'x': x, 'y': y,
        'bytes_raw': len(payload),
        'bytes_br': None,
        'bytes_gz': None,
        'all_nodata': all_nodata,
    }

    # Raw (optional)
    if write_raw and not base.exists():
        write_atomic(base, payload)

    # Brotli
    if generate_br and brotli is not None and not br_path.exists():
        try:
            # Use higher quality for better compression (Q10: 9% smaller, minimal decode overhead)
            br = brotli.compress(payload, quality=10)  # type: ignore[arg-type]
            write_atomic(br_path, br)
            stats['bytes_br'] = len(br)
        except Exception:
            # Skip brotli on failure
            pass

    # Gzip
    if generate_gz and not gz_path.exists():
        try:
            gz = gzip.compress(payload, compresslevel=1)
            write_atomic(gz_path, gz)
            stats['bytes_gz'] = len(gz)
        except Exception:
            pass

    return stats


def generate_for_zoom(z: int, bbox: Tuple[float, float, float, float], out_dir: Path, workers: int, generate_br: bool, generate_gz: bool, write_raw: bool, loader: ElevationDataLoader, skip_existing: bool = True, max_tasks_inflight: int = 2000) -> dict:
    """Generate tiles for a single zoom level within a bbox.

    Streams tasks to a process pool to cap memory usage.
    Returns a summary dict for this zoom.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    tile_iter = tiles_for_bbox(z, min_lon, min_lat, max_lon, max_lat)

    submitted = 0
    completed = 0
    have = 0
    skipped_missing = 0
    bytes_raw = 0
    bytes_br = 0
    bytes_gz = 0

    t0 = time.time()

    with cf.ProcessPoolExecutor(max_workers=workers) as pool:
        futures: set[cf.Future] = set()

        def submit_next(batch: Iterable[Tile]) -> None:
            nonlocal submitted
            for t in batch:
                fut = pool.submit(process_tile, t.z, t.x, t.y, out_dir, generate_br, generate_gz, write_raw, loader, skip_existing)
                futures.add(fut)
                submitted += 1

        # Pre-fill the queue
        batch_size = max(1000, workers * 200)
        batch: list[Tile] = []
        for t in tile_iter:
            batch.append(t)
            if len(futures) < max_tasks_inflight and len(batch) >= batch_size:
                submit_next(batch)
                batch = []
            # Keep pumping while we have capacity
            while len(futures) >= max_tasks_inflight:
                done, futures = cf.wait(futures, return_when=cf.FIRST_COMPLETED)
                for d in done:
                    completed += 1
                    res = d.result()
                    if res is not None:
                        if res.get('skipped_missing'):
                            skipped_missing += 1
                        else:
                            have += 1
                            bytes_raw += res.get('bytes_raw') or 0
                            bytes_br += res.get('bytes_br') or 0
                            bytes_gz += res.get('bytes_gz') or 0

        # Submit any remaining tiles in the last batch
        if batch:
            submit_next(batch)

        # Drain the queue
        while futures:
            done, futures = cf.wait(futures, return_when=cf.FIRST_COMPLETED)
            for d in done:
                completed += 1
                res = d.result()
                if res is not None:
                    if res.get('skipped_missing'):
                        skipped_missing += 1
                    else:
                        have += 1
                        bytes_raw += res.get('bytes_raw') or 0
                        bytes_br += res.get('bytes_br') or 0
                        bytes_gz += res.get('bytes_gz') or 0

    t1 = time.time()

    return {
        'z': z,
        'tiles_examined': submitted,
        'tiles_written': have,
        'tiles_skipped_missing': skipped_missing,
        'elapsed_sec': round(t1 - t0, 2),
        'bytes_raw': bytes_raw,
        'bytes_br': bytes_br,
        'bytes_gz': bytes_gz,
    }


def write_manifest(out_dir: Path, summary: dict) -> None:
    manifest_path = out_dir / 'manifest.json'
    ensure_dir(out_dir)
    with open(manifest_path, 'w') as f:
        json.dump(summary, f, indent=2)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Generate pre-compressed elevation tiles')
    ap.add_argument('--output-dir', type=Path, default=Path(os.getenv('PRECOMPRESSED_TILES_DIR') or 'elevation-tiles'), help='Output directory for {z}/{x}/{y} tiles')
    ap.add_argument('--source-dir', type=Path, default=None, help='Override elevation source directory (default: config.ELEVATION_DATA_DIR)')
    ap.add_argument('--zoom-min', type=int, default=8, help='Minimum zoom level (inclusive)')
    ap.add_argument('--zoom-max', type=int, default=15, help='Maximum zoom level (inclusive)')
    ap.add_argument('--bbox', type=float, nargs=4, metavar=('MIN_LON','MIN_LAT','MAX_LON','MAX_LAT'), help='Optional bounding box to constrain generation')
    ap.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 4) - 1), help='Parallel workers (processes)')
    ap.add_argument('--no-br', action='store_true', help='Disable Brotli generation')
    # Default to no gzip: single best format by default is Brotli
    ap.add_argument('--no-gz', action='store_true', default=True, help='Disable Gzip generation (default: disabled)')
    # Default to no raw: reduce storage; enable for debugging if needed
    ap.add_argument('--write-raw', action='store_true', help='Also write raw .u16 alongside .u16.br')
    ap.add_argument('--no-skip', action='store_true', help='Do not skip existing tiles')
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    out_dir: Path = args.output_dir
    zoom_min: int = args.zoom_min
    zoom_max: int = args.zoom_max
    # Resolve source directory loudly and initialize loader
    src_dir = Path(args.source_dir) if args.source_dir else Path(ELEVATION_DATA_DIR)
    if not src_dir.exists():
        print(f"FATAL: Elevation source dir not found: {src_dir}")
        print("Hint: run inside the container or pass --source-dir to a valid path (e.g., data/elevation-source)")
        sys.exit(2)
    zst_files = list(src_dir.glob('*.zst'))
    if len(zst_files) < 100:
        print(f"FATAL: Source dir {src_dir} has only {len(zst_files)} .zst files (expected thousands)")
        print("This usually means you're pointing at the wrong path. Aborting to avoid writing bogus tiles.")
        sys.exit(2)

    # Determine bbox
    if args.bbox:
        bbox = tuple(args.bbox)  # type: ignore[assignment]
    else:
        bbox = discover_coverage_bbox_from_metadata(src_dir)

    loader = ElevationDataLoader(data_dir=src_dir)

    generate_br = not args.no_br
    generate_gz = not args.no_gz  # default False due to default True for --no-gz
    write_raw = bool(args.write_raw)
    skip_existing = not args.no_skip

    overall = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'source_dir': str(src_dir),
        'output_dir': str(out_dir),
        'bbox': {
            'min_lon': bbox[0], 'min_lat': bbox[1], 'max_lon': bbox[2], 'max_lat': bbox[3]
        },
        'zoom_min': zoom_min,
        'zoom_max': zoom_max,
        'variants': [v for v in ['raw', 'br', 'gz'] if ((v != 'br' or generate_br) and (v != 'gz' or generate_gz) and (v != 'raw' or write_raw))],
        'zooms': [],
        'totals': {
            'tiles_written': 0,
            'bytes_raw': 0,
            'bytes_br': 0,
            'bytes_gz': 0,
            'elapsed_sec': 0,
        }
    }

    print(f"➡️  Generating tiles to {out_dir} for z={zoom_min}..{zoom_max} within bbox {bbox}")
    print(f"📦 Using elevation source: {src_dir}  (files: {len(zst_files)})")
    if zoom_max - zoom_min >= 6:
        print("⚠️  Large zoom span selected; expect very large tile counts.")

    t_start = time.time()
    for z in range(zoom_min, zoom_max + 1):
        print(f"→ z={z} ...")
        zsum = generate_for_zoom(
            z=z,
            bbox=bbox, 
            out_dir=out_dir,
            workers=args.workers,
            generate_br=generate_br,
            generate_gz=generate_gz,
            write_raw=write_raw,
            loader=loader,
            skip_existing=skip_existing,
        )
        overall['zooms'].append(zsum)
        overall['totals']['tiles_written'] += zsum['tiles_written']
        # Tally skipped tiles loudly
        overall.setdefault('totals', {}).setdefault('tiles_skipped_missing', 0)
        overall['totals']['tiles_skipped_missing'] += zsum.get('tiles_skipped_missing', 0)
        overall['totals']['bytes_raw'] += zsum['bytes_raw']
        overall['totals']['bytes_br'] += zsum['bytes_br']
        overall['totals']['bytes_gz'] += zsum['bytes_gz']
        write_manifest(out_dir, overall)
        print(f"  ✓ z={z} wrote {zsum['tiles_written']} tiles (skipped missing: {zsum.get('tiles_skipped_missing', 0)}) in {zsum['elapsed_sec']}s")

    overall['totals']['elapsed_sec'] = round(time.time() - t_start, 2)
    write_manifest(out_dir, overall)
    print(f"✅ Done. Wrote {overall['totals']['tiles_written']} tiles across z={zoom_min}..{zoom_max}. Skipped missing: {overall['totals'].get('tiles_skipped_missing', 0)}")


if __name__ == '__main__':
    main()
