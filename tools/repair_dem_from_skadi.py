#!/usr/bin/env python3
"""Repair a 1° DEM source tile from Skadi and optionally regenerate precompressed tiles.

This is intended to run inside the production webapp container (Coolify) so it has:
- Python deps (numpy, zstandard, brotli)
- Access to mounted data paths under `/app/data/*`

Examples (inside container):
  /app/.venv/bin/python /app/tools/repair_dem_from_skadi.py \
    --tile-id n33_w080_1arc_v3 --regen --zoom-min 5 --zoom-max 11 --yes

  /app/.venv/bin/python /app/tools/repair_dem_from_skadi.py \
    --lat 33 --lon -80 --regen --zoom-min 6 --zoom-max 11 --yes
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import shutil
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import zstandard as zstd

try:
    import brotli  # type: ignore
except Exception:  # pragma: no cover
    brotli = None


@dataclass(frozen=True)
class DegreeTile:
    """A 1-degree SRTM/SKADI tile, referenced by its SW corner."""

    lat: int
    lon: int  # signed (west negative)

    @property
    def skadi_name(self) -> str:
        lat_letter = "N" if self.lat >= 0 else "S"
        lon_letter = "E" if self.lon >= 0 else "W"
        return f"{lat_letter}{abs(self.lat):02d}{lon_letter}{abs(self.lon):03d}"

    @property
    def skadi_prefix(self) -> str:
        lat_letter = "N" if self.lat >= 0 else "S"
        return f"{lat_letter}{abs(self.lat):02d}"

    @property
    def internal_id(self) -> str:
        lat_letter = "n" if self.lat >= 0 else "s"
        lon_letter = "e" if self.lon >= 0 else "w"
        return (
            f"{lat_letter}{abs(self.lat):02d}_{lon_letter}{abs(self.lon):03d}_1arc_v3"
        )

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """(min_lon, min_lat, max_lon, max_lat) covering exactly this 1° tile."""
        return (
            float(self.lon),
            float(self.lat),
            float(self.lon + 1),
            float(self.lat + 1),
        )


def _parse_tile_id(tile_id: str) -> DegreeTile:
    # Example: n33_w080_1arc_v3
    parts = tile_id.split("_")
    if len(parts) < 2:
        raise ValueError(f"Unrecognized tile-id: {tile_id}")
    lat_part, lon_part = parts[0], parts[1]
    if len(lat_part) < 2 or len(lon_part) < 2:
        raise ValueError(f"Unrecognized tile-id: {tile_id}")

    lat = int(lat_part[1:])
    if lat_part[0].lower() == "s":
        lat = -lat

    lon = int(lon_part[1:])
    if lon_part[0].lower() == "w":
        lon = -lon

    return DegreeTile(lat=lat, lon=lon)


def _parse_skadi_name(skadi: str) -> DegreeTile:
    # Example: N33W080
    skadi = skadi.strip()
    if len(skadi) != 7:
        raise ValueError(f"Unrecognized skadi name: {skadi}")
    lat_letter = skadi[0].upper()
    lat = int(skadi[1:3])
    if lat_letter == "S":
        lat = -lat
    lon_letter = skadi[3].upper()
    lon = int(skadi[4:7])
    if lon_letter == "W":
        lon = -lon
    return DegreeTile(lat=lat, lon=lon)


def _default_source_dir() -> Path:
    p = Path("/app/data/elevation-source")
    if p.exists():
        return p
    # Local dev fallback
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "data" / "elevation-source"


def _default_tiles_dir() -> Path:
    p = Path("/app/data/elevation-tiles")
    if p.exists():
        return p
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "data" / "elevation-tiles"


def _timestamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _skadi_url(tile: DegreeTile) -> str:
    return (
        "https://s3.amazonaws.com/elevation-tiles-prod/skadi/"
        f"{tile.skadi_prefix}/{tile.skadi_name}.hgt.gz"
    )


def _compute_aligned_bounds(tile: DegreeTile) -> tuple[dict, list[float]]:
    # Existing metadata uses bounds expanded by half a pixel (1/7200°) to align edges.
    pix = 1.0 / 3600.0
    half = pix / 2.0
    left = tile.lon - half
    bottom = tile.lat - half
    right = (tile.lon + 1) + half
    top = (tile.lat + 1) + half
    bounds = {
        "left": float(left),
        "bottom": float(bottom),
        "right": float(right),
        "top": float(top),
    }
    transform = [pix, 0.0, bounds["left"], 0.0, -pix, bounds["top"], 0.0, 0.0, 1.0]
    return bounds, transform


def _download_hgt_gz(url: str, timeout_sec: int = 90) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout_sec) as resp:
        return resp.read()


def _hgt_to_int16(hgt_bytes: bytes) -> np.ndarray:
    # HGT is big-endian signed 16-bit; 3601x3601.
    arr = np.frombuffer(hgt_bytes, dtype=">i2").reshape(3601, 3601).astype(np.int16)
    return arr


def backup_existing(
    source_dir: Path, tile_id: str, repairs_dir: Path | None
) -> Path | None:
    zst = source_dir / f"{tile_id}.zst"
    meta = source_dir / f"{tile_id}.json"
    if not zst.exists() and not meta.exists():
        return None

    if repairs_dir is None:
        repairs_dir = source_dir / "repairs" / _timestamp()

    repairs_dir.mkdir(parents=True, exist_ok=True)
    if zst.exists():
        shutil.copy2(zst, repairs_dir / zst.name)
    if meta.exists():
        shutil.copy2(meta, repairs_dir / meta.name)
    return repairs_dir


def write_source_tile(
    tile: DegreeTile, source_dir: Path, *, zstd_level: int = 3
) -> None:
    url = _skadi_url(tile)
    gz_bytes = _download_hgt_gz(url)
    hgt_bytes = gzip.decompress(gz_bytes)
    arr = _hgt_to_int16(hgt_bytes)

    bounds, transform = _compute_aligned_bounds(tile)

    raw = arr.tobytes()
    cctx = zstd.ZstdCompressor(level=zstd_level)
    compressed = cctx.compress(raw)

    tile_id = tile.internal_id
    out_zst = source_dir / f"{tile_id}.zst"
    out_json = source_dir / f"{tile_id}.json"

    out_zst.write_bytes(compressed)
    out_json.write_text(
        json.dumps(
            {
                "tile_id": tile_id,
                "bounds": bounds,
                "transform": transform,
                "crs": "EPSG:4326",
                "shape": [3601, 3601],
                "dtype": "int16",
                "original_size": len(raw),
                "compressed_size": len(compressed),
                "compression_ratio": (len(raw) / len(compressed))
                if len(compressed)
                else None,
                "nodata_value": -32768,
                "source": url,
            },
            indent=2,
        )
        + "\n"
    )


def _deg2num(lat_deg: float, lon_deg: float, zoom: int) -> tuple[int, int]:
    lat_rad = math.radians(lat_deg)
    n = 2.0**zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile


def _elevation_to_u16(
    elev: np.ndarray | None, *, nodata_value: int = -32768
) -> np.ndarray:
    # Matches server-side normalization: [-500..9000] => [0..65534], NODATA => 65535
    if elev is None:
        return np.full((256, 256), 65535, dtype=np.uint16)

    normalized = np.zeros_like(elev, dtype=np.float32)
    nodata_mask = (elev == nodata_value) | (elev < -500) | (elev > 9000)
    valid_mask = ~nodata_mask
    normalized[valid_mask] = np.clip(
        (elev[valid_mask].astype(np.float32) + 500.0) / 9500.0 * 65534.0,
        0.0,
        65534.0,
    )
    normalized[nodata_mask] = 65535.0
    return normalized.astype(np.uint16)


def regen_precompressed(
    *,
    bbox: tuple[float, float, float, float],
    tiles_dir: Path,
    zoom_min: int,
    zoom_max: int,
    margin_tiles: int,
    overwrite: bool,
) -> dict:
    if brotli is None:
        raise RuntimeError("brotli is not available; cannot write .u16.br tiles")

    # Lazy imports: require running within the API environment (inside container).
    from elevation_loader import elevation_loader  # type: ignore

    min_lon, min_lat, max_lon, max_lat = bbox

    written = 0
    all_nodata_tiles = 0
    started = time.time()

    for z in range(zoom_min, zoom_max + 1):
        # NW + SE corners to derive tile bounds
        x0, y0 = _deg2num(max_lat, min_lon, z)
        x1, y1 = _deg2num(min_lat, max_lon, z)
        x_min, x_max = min(x0, x1), max(x0, x1)
        y_min, y_max = min(y0, y1), max(y0, y1)

        x_min = max(0, x_min - margin_tiles)
        y_min = max(0, y_min - margin_tiles)
        x_max = x_max + margin_tiles
        y_max = y_max + margin_tiles

        for x in range(x_min, x_max + 1):
            x_dir = tiles_dir / str(z) / str(x)
            x_dir.mkdir(parents=True, exist_ok=True)
            for y in range(y_min, y_max + 1):
                out_path = x_dir / f"{y}.u16.br"
                if out_path.exists() and not overwrite:
                    continue

                elev = elevation_loader.get_elevation_for_tile(x, y, z, tile_size=256)
                u16 = _elevation_to_u16(elev)
                if bool(np.all(u16 == 65535)):
                    all_nodata_tiles += 1
                out_path.write_bytes(brotli.compress(u16.tobytes(), quality=1))
                written += 1

                # Keep the in-process cache bounded for bulk writes
                elevation_loader.cache.clear()

    return {
        "written": written,
        "all_nodata_tiles": all_nodata_tiles,
        "elapsed_sec": time.time() - started,
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)

    src = ap.add_argument_group("Tile Selection (pick one)")
    src.add_argument("--tile-id", help="Internal tile id, e.g. n33_w080_1arc_v3")
    src.add_argument("--skadi", help="Skadi tile name, e.g. N33W080")
    src.add_argument(
        "--lat", type=int, help="Tile SW corner latitude (integer degrees)"
    )
    src.add_argument(
        "--lon",
        type=int,
        help="Tile SW corner longitude (integer degrees, west negative)",
    )

    ap.add_argument("--source-dir", type=Path, default=_default_source_dir())
    ap.add_argument("--tiles-dir", type=Path, default=_default_tiles_dir())
    ap.add_argument(
        "--repairs-dir", type=Path, default=None, help="Override backups location"
    )

    ap.add_argument(
        "--regen",
        action="store_true",
        help="Regenerate precompressed tiles for this 1° bbox",
    )
    ap.add_argument("--zoom-min", type=int, default=5)
    ap.add_argument("--zoom-max", type=int, default=11)
    ap.add_argument(
        "--margin-tiles", type=int, default=1, help="Tile margin around bbox per zoom"
    )
    ap.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing .u16.br tiles"
    )

    ap.add_argument(
        "--yes",
        action="store_true",
        help="Proceed without prompting (required for writes in automated runs)",
    )
    ap.add_argument("--dry-run", action="store_true", help="Print actions and exit")
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    if args.tile_id:
        tile = _parse_tile_id(args.tile_id)
    elif args.skadi:
        tile = _parse_skadi_name(args.skadi)
    elif args.lat is not None and args.lon is not None:
        tile = DegreeTile(lat=args.lat, lon=args.lon)
    else:
        raise SystemExit("Provide --tile-id, --skadi, or --lat/--lon.")

    source_dir: Path = args.source_dir
    tiles_dir: Path = args.tiles_dir
    repairs_dir: Path | None = args.repairs_dir

    url = _skadi_url(tile)
    tile_id = tile.internal_id
    bbox = tile.bbox

    print("tile_id:", tile_id)
    print("skadi:", tile.skadi_name)
    print("url:", url)
    print("source_dir:", source_dir)
    print("tiles_dir:", tiles_dir)
    print("bbox:", bbox)
    if args.regen:
        print(
            "regen:",
            True,
            "zoom:",
            f"{args.zoom_min}..{args.zoom_max}",
            "margin_tiles:",
            args.margin_tiles,
        )

    if args.dry_run:
        return

    if not args.yes:
        raise SystemExit("Refusing to write without --yes.")

    source_dir.mkdir(parents=True, exist_ok=True)

    try:
        backed_up = backup_existing(source_dir, tile_id, repairs_dir)
    except PermissionError as e:
        raise SystemExit(
            f"Permission denied creating backups under {source_dir}. "
            "Re-run as a user with write permission (in prod: docker exec -u 0), "
            "or pass --repairs-dir to a writable path.\n"
            f"Details: {e}"
        ) from e

    if backed_up:
        print("backup_dir:", backed_up)

    print("downloading + writing source...")
    write_source_tile(tile, source_dir)
    print("wrote source:", source_dir / f"{tile_id}.zst")

    if args.regen:
        print("regenerating precompressed tiles...")
        stats = regen_precompressed(
            bbox=bbox,
            tiles_dir=tiles_dir,
            zoom_min=args.zoom_min,
            zoom_max=args.zoom_max,
            margin_tiles=args.margin_tiles,
            overwrite=bool(args.overwrite),
        )
        print("regen_stats:", stats)


if __name__ == "__main__":
    main()
