from __future__ import annotations

import numpy as np
import pytest

from tools.hand.convert_precomputed_hand import (
    U16_NODATA,
    build_single_region_manifest,
    encode_hand_window,
    percentile_from_histogram,
    summarize_histogram,
    update_histogram,
)


def test_encode_hand_window_decimeters_and_nodata() -> None:
    values = np.array(
        [
            [0.0, 1.24, np.nan],
            [-1.0, -9999.0, 7000.0],
        ],
        dtype=np.float32,
    )

    encoded, valid = encode_hand_window(values, source_nodata=-9999.0)

    assert encoded.tolist() == [
        [0, 12, U16_NODATA],
        [U16_NODATA, U16_NODATA, U16_NODATA - 1],
    ]
    assert valid.tolist() == [
        [True, True, False],
        [False, False, True],
    ]


def test_histogram_summary_reports_meter_quantiles() -> None:
    histogram = np.zeros(U16_NODATA, dtype=np.int64)
    encoded = np.array(
        [
            [0, 10, 20],
            [20, U16_NODATA, U16_NODATA],
        ],
        dtype=np.uint16,
    )

    valid_count = update_histogram(histogram, encoded)
    summary = summarize_histogram(histogram, total_cells=encoded.size)

    assert valid_count == 4
    assert percentile_from_histogram(histogram, 50) == 1.0
    assert summary["valid_cells"] == 4
    assert summary["nodata_cells"] == 2
    assert summary["hand_m"] == {
        "min": 0.0,
        "p50": 1.0,
        "p95": 2.0,
        "p99": 2.0,
        "max": 2.0,
    }
    assert summary["cells_below_threshold_ft"]["3"]["cells"] == 1


def test_build_single_region_manifest_shape(tmp_path) -> None:
    cog = tmp_path / "hand.cog.tif"
    manifest = build_single_region_manifest(
        dataset_version="ornl-cfim-v0p21-010700",
        region_id="huc6-010700",
        output_cog=cog,
        crs="EPSG:4269",
        bounds=(-72.1, 42.1, -70.8, 44.2),
        source_metadata={
            "name": "ORNL CFIM v0.21",
            "license": "CC BY 4.0",
        },
    )

    region = manifest["layers"]["hand"]["regions"][0]
    assert manifest["dataset_version"] == "ornl-cfim-v0p21-010700"
    assert manifest["layers"]["hand"]["encoding"] == "uint16-decimeters"
    assert manifest["layers"]["hand"]["nodata"] == U16_NODATA
    assert manifest["source"] == {
        "name": "ORNL CFIM v0.21",
        "license": "CC BY 4.0",
    }
    assert region["id"] == "huc6-010700"
    assert region["url"] == str(cog)


@pytest.mark.parametrize("percentile", [0, 101])
def test_percentile_clamps_to_histogram_extent(percentile: float) -> None:
    histogram = np.zeros(U16_NODATA, dtype=np.int64)
    histogram[7] = 1

    assert percentile_from_histogram(histogram, percentile) == 0.7
