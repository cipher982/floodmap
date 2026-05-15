from __future__ import annotations

import json

from tools.hand.run_reference_gate import (
    compare_command,
    load_metrics,
    metrics_path,
    write_sensitivity_report,
)


def sample_metrics(*, all_touched: bool) -> dict:
    return {
        "all_touched": all_touched,
        "fema_total_cells": 1000 if all_touched else 900,
        "fema_in_hand_nodata_cells": 100 if all_touched else 80,
        "fema_in_hand_nodata_pct": 10.0 if all_touched else 8.888,
        "thresholds": [
            {
                "threshold_ft": 3.0,
                "precision": 0.4 if all_touched else 0.35,
                "recall": 0.5 if all_touched else 0.45,
                "precision_lift_vs_low_elevation": 2.0 if all_touched else 1.8,
            },
            {
                "threshold_ft": 1.0,
                "precision": 0.5 if all_touched else 0.45,
                "recall": 0.3 if all_touched else 0.25,
                "precision_lift_vs_low_elevation": 2.5 if all_touched else 2.2,
            },
        ],
    }


def test_metrics_path_and_load_metrics(tmp_path) -> None:
    path = metrics_path(tmp_path / "run", "region-a")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"ok": True}), encoding="utf-8")

    assert path == tmp_path / "run" / "region-a" / "metrics.json"
    assert load_metrics(path) == {"ok": True}


def test_write_sensitivity_report_orders_thresholds(tmp_path) -> None:
    output_path = tmp_path / "sensitivity.md"

    write_sensitivity_report(
        all_touched_metrics=sample_metrics(all_touched=True),
        strict_metrics=sample_metrics(all_touched=False),
        output_path=output_path,
    )

    report = output_path.read_text(encoding="utf-8")
    assert "FEMA cells 1,000" in report
    assert "| 1 ft | 0.500 | 0.450 | 0.300 | 0.250 | 2.500 | 2.200 |" in report
    assert "| 3 ft | 0.400 | 0.350 | 0.500 | 0.450 | 2.000 | 1.800 |" in report
    assert report.index("| 1 ft |") < report.index("| 3 ft |")


def test_compare_command_adds_no_all_touched_flag(tmp_path) -> None:
    command = compare_command(
        script=tmp_path / "compare_to_reference.py",
        manifest=tmp_path / "manifest.json",
        region="region-a",
        output_dir=tmp_path / "out",
        cache_dir=tmp_path / "cache",
        baseline_raster=tmp_path / "elevation.tif",
        chunk_size=50,
        simplify_m=3.0,
        max_image_dim=1200,
        all_touched=False,
    )

    assert "--no-all-touched" in command
    assert command[1].endswith("compare_to_reference.py")
    assert command[command.index("--region") + 1] == "region-a"
    assert command[command.index("--baseline-raster") + 1].endswith("elevation.tif")
