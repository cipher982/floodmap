"""Validate that the tile extraction pipeline returns *usable* data.

We focus on three separate criteria:

1. The tile must contain more than one unique value – otherwise the colourful
   flood-layer degrades to a single block.
2. The share of NoData pixels should stay below 50 %.  Some degree tiles are
   mostly water so we cannot demand a tiny percentage here.
3. An adjacency check between two neighbouring tiles makes sure that the
   rightmost column of the *left* tile and the leftmost column of the *right*
   tile are similar (difference < 5 m for 90 % of the pixels).  This catches
   off-by-one errors in the coordinate transform.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.api.elevation_loader import elevation_loader

ZOOM = 8
XTILE = 68  # Tampa area – known to expose previous bugs
YTILE = 106


def _get_tile(x: int, y: int) -> np.ndarray:
    return elevation_loader.get_elevation_for_tile(x, y, ZOOM)


def test_tile_has_variation() -> None:
    tile = _get_tile(XTILE, YTILE)
    unique_vals = np.unique(tile)

    assert unique_vals.size > 2, "Tile contains fewer than 3 unique elevation values"


def test_nodata_ratio() -> None:
    tile = _get_tile(XTILE, YTILE)
    nodata_ratio = np.count_nonzero(tile == -32768) / tile.size

    assert nodata_ratio < 0.5, "Too many NoData pixels in tile – suspect wrong indices"


def test_adjacent_tile_alignment() -> None:
    left_tile = _get_tile(XTILE, YTILE)
    right_tile = _get_tile(XTILE + 1, YTILE)

    # Compare border columns
    left_edge = left_tile[:, -1]
    right_edge = right_tile[:, 0]

    # Ignore NoData pixels when comparing
    mask = (left_edge != -32768) & (right_edge != -32768)
    diffs = np.abs(left_edge[mask] - right_edge[mask])

    if diffs.size == 0:
        pytest.skip(
            "No overlapping valid data at tile boundary – cannot test alignment"
        )

    # 90 % of the compared values must be within ±5 metres
    within_threshold = np.count_nonzero(diffs <= 5) / diffs.size

    assert within_threshold >= 0.9, "Significant mis-alignment between adjacent tiles"
