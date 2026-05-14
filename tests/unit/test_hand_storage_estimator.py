from tools.hand.storage_estimator import (
    BBox,
    SourceRasterEstimate,
    estimate_pyramid,
    format_bytes,
    tile_count_for_bbox,
)


def test_birmingham_tile_counts_match_generated_artifact_bbox():
    bbox = BBox("Birmingham", -87.02, 33.30, -86.52, 33.75)

    assert [tile_count_for_bbox(bbox, z) for z in range(9, 13)] == [2, 6, 16, 49]


def test_conus_z14_bbox_estimate_order_of_magnitude():
    conus = BBox("CONUS", -125.0, 24.0, -66.5, 49.5)
    estimate = estimate_pyramid(conus, 9, 14)

    assert estimate.total_tiles == 5_243_329
    assert 680_000_000_000 < estimate.total_raw_bytes < 690_000_000_000


def test_source_raster_estimate_uses_cell_area_and_overview_multiplier():
    estimate = SourceRasterEstimate("test", area_km2=100, cell_size_m=10)

    assert estimate.cell_count == 1_000_000
    assert estimate.raw_bytes == 2_000_000
    assert estimate.raw_bytes_with_overviews == 2_666_667


def test_format_bytes_uses_decimal_units():
    assert format_bytes(128) == "128 B"
    assert format_bytes(128_000) == "128.0 KB"
