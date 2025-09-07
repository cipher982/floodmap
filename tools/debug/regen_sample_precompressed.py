#!/usr/bin/env python3
"""
Regenerate a sample precompressed elevation tile from local source data.

Uses the production elevation loader logic but points to the host path
`data/elevation-source` so it can be run outside the container.

Writes outputs to `output_sample/{z}/{x}/{y}.u16` and `.u16.br`.
Prints basic stats to confirm non-NODATA content.
"""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass

import gzip

import brotli

import sys
ROOT = Path(__file__).resolve().parents[2]  # project root
sys.path.insert(0, str(ROOT / 'src' / 'api'))

from elevation_loader import ElevationDataLoader
from config import TILE_SIZE, NODATA_VALUE


def normalize_to_uint16(elevation_data):
    import numpy as np
    if elevation_data is None:
        return np.full((TILE_SIZE, TILE_SIZE), 65535, dtype=np.uint16).tobytes()
    normalized = np.zeros_like(elevation_data, dtype=np.float32)
    nodata_mask = (elevation_data == NODATA_VALUE) | (elevation_data < -500) | (elevation_data > 9000)
    valid_mask = ~nodata_mask
    normalized[valid_mask] = np.clip((elevation_data[valid_mask] + 500) / 9500 * 65534, 0, 65534)
    normalized[nodata_mask] = 65535
    return normalized.astype('uint16').tobytes()


def stats_u16(data: bytes) -> str:
    from array import array
    a = array('H'); a.frombytes(data)
    tot = len(a)
    mn = min(a); mx = max(a)
    nodata = sum(1 for v in a if v == 65535)
    zeros = sum(1 for v in a if v == 0)
    return f"bytes={len(data)} min={mn} max={mx} nodata%={nodata*100.0/tot:.2f}% zeros%={zeros*100.0/tot:.2f}%"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--z', type=int, required=True)
    ap.add_argument('--x', type=int, required=True)
    ap.add_argument('--y', type=int, required=True)
    ap.add_argument('--src', type=Path, default=Path('data/elevation-source'))
    ap.add_argument('--out', type=Path, default=Path('output_sample'))
    args = ap.parse_args()

    loader = ElevationDataLoader(data_dir=args.src)
    arr = loader.get_elevation_for_tile(args.x, args.y, args.z, tile_size=TILE_SIZE)
    payload = normalize_to_uint16(arr)

    out_dir = args.out / str(args.z) / str(args.x)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"{args.y}.u16"
    base.write_bytes(payload)

    if brotli:
        br = brotli.compress(payload, quality=10)  # Q10
        (out_dir / f"{args.y}.u16.br").write_bytes(br)

        # Verify round-trip
        import brotli as _br
        dec = _br.decompress(br)
        print("runtime:", stats_u16(payload))
        print("br-dec:", stats_u16(dec))
        if dec != payload:
            print("WARNING: decompressed payload differs from original")
    else:
        print("brotli not available; wrote only .u16")

    print(f"Wrote samples to {out_dir}")


if __name__ == '__main__':
    main()

