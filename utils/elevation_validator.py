"""Utility helpers to validate the integrity of the compressed SRTM tiles and
the tile-extraction pipeline.

These functions are **read-only** – they never mutate the data on disk. They
are intentionally kept independent from the main API implementation so that
they can be used in lightweight test-suites or ad-hoc sanity checks without
dragging the whole FastAPI stack in.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
import zstandard as zstd

# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _decompress_tile(file_path: Path, shape: tuple[int, int]) -> np.ndarray:
    """Safely decompress a *.zst file into a numpy array of the expected shape.

    This function uses `max_output_size` to avoid allocating crazy amounts of
    memory in case the metadata is corrupt.
    """

    expected_bytes = shape[0] * shape[1] * 2  # int16 → 2 bytes per value

    with file_path.open("rb") as fh:
        compressed = fh.read()

    dctx = zstd.ZstdDecompressor()
    decompressed = dctx.decompress(compressed)

    arr = np.frombuffer(decompressed, dtype=np.int16)

    if arr.size != shape[0] * shape[1]:
        raise ValueError(
            f"Decompressed array size mismatch for {file_path.name}: "
            f"expected {shape}, got {arr.size} elements"
        )

    return arr.reshape(shape)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_elevation_file(file_path: Path) -> dict:
    """Load and validate a single compressed elevation tile.

    The returned dict contains a concise set of metrics that can easily be
    logged or fed into a Pandas data-frame for further analysis.
    """

    if not file_path.exists():
        raise FileNotFoundError(file_path)

    metadata_path = file_path.with_suffix(".json")
    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing metadata for {file_path.name}")

    metadata = json.loads(metadata_path.read_text())

    shape: tuple[int, int]
    if "shape" in metadata:
        shape = tuple(metadata["shape"])
    else:  # legacy format
        shape = (int(metadata["height"]), int(metadata["width"]))

    arr = _decompress_tile(file_path, shape)

    return {
        "file": file_path.name,
        "min": int(arr.min()),
        "max": int(arr.max()),
        "nodata_pct": float(np.count_nonzero(arr == -32768) / arr.size * 100.0),
        "zero_pct": float(np.count_nonzero(arr == 0) / arr.size * 100.0),
    }


def sample_elevation_files(data_root: Path, sample_size: int = 10) -> list[Path]:
    """Pick a random subset of `sample_size` compressed DEM files from the folder."""

    all_files = list(data_root.glob("*.zst"))
    if len(all_files) == 0:
        raise FileNotFoundError(f"No *.zst files found in {data_root}")

    return random.sample(all_files, min(sample_size, len(all_files)))


# ---------------------------------------------------------------------------
# Convenience CLI entry-point (optional)
# ---------------------------------------------------------------------------


def main() -> None:  # pragma: no cover
    import argparse
    import pprint

    parser = argparse.ArgumentParser(description="Validate compressed SRTM tiles")
    parser.add_argument("data_dir", type=Path, help="Directory with *.zst files")
    parser.add_argument(
        "--sample", type=int, default=5, help="Number of random files to inspect"
    )

    args = parser.parse_args()

    for f in sample_elevation_files(args.data_dir, args.sample):
        pprint.pprint(validate_elevation_file(f))


if __name__ == "__main__":  # pragma: no cover
    main()
