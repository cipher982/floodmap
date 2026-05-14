from __future__ import annotations

import numpy as np
import pytest
from terrain import TILE_SIZE, U16_TILE_BYTES
from terrain_cog import (
    clear_cog_tile_cache,
    render_cog_tile,
    render_cog_tile_with_cache,
    sample_cog_point,
    tile_transform_mercator,
)

rasterio = pytest.importorskip("rasterio")


def write_webmercator_raster(path):
    values = (
        np.arange(TILE_SIZE * TILE_SIZE, dtype=np.uint32).reshape(TILE_SIZE, TILE_SIZE)
        % 1000
    ).astype(np.uint16)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=TILE_SIZE,
        height=TILE_SIZE,
        count=1,
        dtype="uint16",
        crs="EPSG:3857",
        transform=tile_transform_mercator(0, 0, 0),
        nodata=65535,
    ) as dataset:
        dataset.write(values, 1)
    return values


def test_render_cog_tile_returns_exact_u16_tile_for_matching_grid(tmp_path):
    source_path = tmp_path / "source.tif"
    expected = write_webmercator_raster(source_path)

    payload, elapsed_ms = render_cog_tile(source_path, z=0, x=0, y=0)
    actual = np.frombuffer(payload, dtype=np.uint16).reshape(TILE_SIZE, TILE_SIZE)

    assert len(payload) == U16_TILE_BYTES
    assert elapsed_ms >= 0
    np.testing.assert_array_equal(actual, expected)


def test_render_cog_tile_cache_marks_second_read_as_hit(tmp_path):
    source_path = tmp_path / "source.tif"
    write_webmercator_raster(source_path)
    clear_cog_tile_cache()

    _, first_status, _ = render_cog_tile_with_cache(source_path, z=0, x=0, y=0)
    _, second_status, _ = render_cog_tile_with_cache(source_path, z=0, x=0, y=0)

    assert first_status == "MISS"
    assert second_status == "HIT"


def test_sample_cog_point_reads_single_encoded_pixel(tmp_path):
    source_path = tmp_path / "source.tif"
    values = write_webmercator_raster(source_path)

    sampled = sample_cog_point(source_path, lon=0.0, lat=0.0)

    # The Web Mercator origin is on a pixel boundary for this synthetic grid;
    # rasterio floors that to the northwest pixel.
    assert sampled == int(values[127, 127])
