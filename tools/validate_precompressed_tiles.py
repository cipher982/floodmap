#!/usr/bin/env python3
"""
Smart validator for precompressed elevation tiles (.u16.br/.u16.gz).

What it does
  - Scans a tile tree {z}/{x}/{y}.u16.br under a directory
  - Summarises per-zoom counts and size buckets
  - Randomly samples tiles and measures nodata%/min/max after decompress
  - Optional: validates via API (precompressed) instead of local files

Usage (local files):
  python tools/validate_precompressed_tiles.py \
    --tiles-dir data/elevation-tiles \
    --zooms 8 9 10 11 \
    --samples 200

Usage (API check):
  python tools/validate_precompressed_tiles.py \
    --api http://127.0.0.1:8000 \
    --zooms 9 10 11 \
    --samples 50

Notes
  - For .br, this script prefers Python 'brotli' if installed; otherwise it
    shells out to the 'brotli' CLI ('brotli -d -c').
  - For .gz, uses Python 'gzip'.
  - Keeps dependencies minimal; falls back gracefully when tools are missing.
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


BR_AVAILABLE = False
try:
    import brotli  # type: ignore
    BR_AVAILABLE = True
except Exception:
    BR_AVAILABLE = False


def decompress_br(data: bytes) -> bytes:
    if BR_AVAILABLE:
        import brotli as _br  # type: ignore
        return _br.decompress(data)
    # Fall back to brotli CLI if present
    if shutil.which('brotli'):
        p = subprocess.run(['brotli', '-d', '-c'], input=data, capture_output=True, check=True)
        return p.stdout
    raise RuntimeError("No brotli support (install 'brotli' Python package or CLI)")


def decompress_gz(data: bytes) -> bytes:
    import gzip
    return gzip.decompress(data)


def stats_u16(payload: bytes) -> tuple[int, int, float]:
    from array import array
    a = array('H')
    a.frombytes(payload)
    if not a:
        return (0, 0, 100.0)
    mn = min(a)
    mx = max(a)
    nod = sum(1 for v in a if v == 65535)
    nodata_pct = nod * 100.0 / len(a)
    return (mn, mx, nodata_pct)


@dataclass
class ZoomSummary:
    zoom: int
    files: int
    size_bytes: int
    lt5k: int
    bt5_20k: int
    gt20k: int
    gt100k: int


def human(n: int) -> str:
    for unit in ['B','K','M','G','T']:
        if n < 1024:
            return f"{n}{unit}"
        n //= 1024
    return f"{n}P"


def gather_zoom_summary(root: Path, z: int) -> ZoomSummary:
    files = list(root.glob(f"{z}/**/*.u16.br")) + list(root.glob(f"{z}/**/*.u16.gz"))
    size_bytes = sum(p.stat().st_size for p in files)
    lt5, bt5_20, gt20, gt100 = 0, 0, 0, 0
    for p in files:
        sz = p.stat().st_size
        if sz < 5 * 1024:
            lt5 += 1
        elif sz < 20 * 1024:
            bt5_20 += 1
        else:
            gt20 += 1
        if sz > 100 * 1024:
            gt100 += 1
    return ZoomSummary(z, len(files), size_bytes, lt5, bt5_20, gt20, gt100)


def sample_paths(root: Path, z: int, n: int) -> list[Path]:
    files = list(root.glob(f"{z}/**/*.u16.br")) + list(root.glob(f"{z}/**/*.u16.gz"))
    if not files:
        return []
    # Prefer stratified sampling by size bucket to include both land and ocean tiles
    small = [p for p in files if p.stat().st_size < 5 * 1024]
    mid = [p for p in files if 5 * 1024 <= p.stat().st_size < 20 * 1024]
    large = [p for p in files if p.stat().st_size >= 20 * 1024]
    out: list[Path] = []
    for bucket in (large, mid, small):
        k = max(1, n // 3)
        out.extend(random.sample(bucket, k=min(k, len(bucket))))
    # Top-up if needed
    if len(out) < n:
        left = n - len(out)
        remainder = [p for p in files if p not in out]
        if remainder:
            out.extend(random.sample(remainder, k=min(left, len(remainder))))
    random.shuffle(out)
    return out[:n]


def validate_local(files: Iterable[Path]) -> list[tuple[Path, int, int, float]]:
    results = []
    for p in files:
        b = p.read_bytes()
        if p.suffix == '.gz':
            dec = decompress_gz(b)
        else:
            dec = decompress_br(b)
        mn, mx, nod = stats_u16(dec)
        results.append((p, mn, mx, nod))
    return results


def validate_api(api: str, files: Iterable[Path]) -> list[tuple[str, int, int, float]]:
    import urllib.request
    results = []
    opener = urllib.request.build_opener()
    opener.addheaders = [("Accept-Encoding", "br,gzip")]
    for p in files:
        # Extract z/x/y from path
        parts = p.parts
        # .../tiles_dir/z/x/y.u16.br
        z = parts[-3]; x = parts[-2]; y = p.stem.split('.')[0]
        url = f"{api}/api/v1/tiles/elevation-data/{z}/{x}/{y}.u16?method=precompressed"
        with opener.open(url, timeout=30) as r:
            data = r.read()
            # Decompress based on response header
            enc = r.headers.get('Content-Encoding', '')
            if 'br' in enc:
                dec = decompress_br(data)
            elif 'gzip' in enc:
                dec = decompress_gz(data)
            else:
                dec = data
        mn, mx, nod = stats_u16(dec)
        results.append((url, mn, mx, nod))
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate precompressed tiles (.u16.br/.u16.gz)")
    ap.add_argument('--tiles-dir', type=Path, default=Path('data/elevation-tiles'))
    ap.add_argument('--zooms', type=int, nargs='+', default=[8,9,10,11])
    ap.add_argument('--samples', type=int, default=100, help='Samples per zoom')
    ap.add_argument('--api', type=str, default=None, help='Optional API base (e.g., http://127.0.0.1:8000)')
    args = ap.parse_args()

    root: Path = args.tiles-dir
    if not root.exists():
        print(f"Tiles dir not found: {root}")
        sys.exit(2)

    print(f"Scanning {root} ...")
    total_files = 0
    total_bytes = 0
    summaries: list[ZoomSummary] = []
    for z in args.zooms:
        s = gather_zoom_summary(root, z)
        summaries.append(s)
        total_files += s.files
        total_bytes += s.size_bytes
        print(f"z={s.zoom:>2} files={s.files:>6} size={human(s.size_bytes):>6}  buckets: <5KB={s.lt5k:>5} 5-20KB={s.bt5_20k:>5} >20KB={s.gt20k:>6} >100KB={s.gt100k:>4}")

    print(f"Total: files={total_files} size={human(total_bytes)}")

    # Sampling & validation
    print("\nSampling & decoding:")
    for z in args.zooms:
        files = sample_paths(root, z, args.samples)
        if not files:
            print(f"z={z}: no files")
            continue
        if args.api:
            results = validate_api(args.api, files)
        else:
            results = validate_local(files)
        # Summarise nodata distribution
        nodatas = [r[3] for r in results]
        if not nodatas:
            print(f"z={z}: no results")
            continue
        nodatas_sorted = sorted(nodatas)
        p50 = nodatas_sorted[len(nodatas_sorted)//2]
        p90 = nodatas_sorted[int(len(nodatas_sorted)*0.9)]
        p99 = nodatas_sorted[int(len(nodatas_sorted)*0.99)]
        print(f"z={z}: samples={len(results)} nodata%% p50={p50:.2f} p90={p90:.2f} p99={p99:.2f}")
        # Show a couple of examples
        show = results[:3]
        for r in show:
            ident = r[0] if isinstance(r[0], str) else str(r[0])
            print(f"  {ident} -> min={r[1]} max={r[2]} nodata%={r[3]:.2f}")

    print("\nDone.")


if __name__ == '__main__':
    main()

