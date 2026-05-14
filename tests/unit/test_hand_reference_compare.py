from pathlib import Path

import numpy as np
import pytest

from tools.hand.compare_to_reference import (
    U16_NODATA,
    HandRegion,
    cache_path_for_region,
    compute_metrics,
    local_manifest_path,
)


def test_local_manifest_path_accepts_local_paths_and_file_urls():
    assert local_manifest_path("/tmp/flood map/hand.tif") == Path(
        "/tmp/flood map/hand.tif"
    )
    assert local_manifest_path("file:///tmp/flood%20map/hand.tif") == Path(
        "/tmp/flood map/hand.tif"
    )

    with pytest.raises(ValueError, match="Only local HAND COG paths"):
        local_manifest_path("s3://example-bucket/hand.tif")


def test_compute_metrics_includes_same_coverage_random_baseline():
    hand_values = np.array(
        [
            [0, 5, 20],
            [U16_NODATA, 5, 20],
        ],
        dtype=np.uint16,
    )
    fema_mask = np.array(
        [
            [True, False, False],
            [False, True, False],
        ],
        dtype=np.bool_,
    )

    metrics = compute_metrics(
        hand_values=hand_values,
        fema_mask=fema_mask,
        thresholds_ft=[1.0],
    )[0]

    assert metrics["valid_cells"] == 5
    assert metrics["fema_cells"] == 2
    assert metrics["hand_cells"] == 1
    assert metrics["true_positive"] == 1
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 0.5
    assert metrics["expected_random_precision"] == pytest.approx(0.4)
    assert metrics["precision_lift_vs_random"] == pytest.approx(2.5)


def test_compute_metrics_handles_empty_hand_threshold():
    hand_values = np.array([[20, 30]], dtype=np.uint16)
    fema_mask = np.array([[True, False]], dtype=np.bool_)

    metrics = compute_metrics(
        hand_values=hand_values,
        fema_mask=fema_mask,
        thresholds_ft=[1.0],
    )[0]

    assert metrics["hand_cells"] == 0
    assert metrics["expected_random_precision"] is None
    assert metrics["precision_lift_vs_random"] is None


def test_fema_cache_path_includes_simplification_distance():
    region = HandRegion(
        id="test-region",
        bbox=(-1.0, -1.0, 1.0, 1.0),
        url=Path("/tmp/hand.tif"),
        crs="EPSG:5070",
    )

    path = cache_path_for_region(Path("/cache"), region, 5070, 2.5)

    assert path.name == "test-region-fema-sfha-epsg5070-offset2p5m.json.gz"
