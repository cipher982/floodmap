from __future__ import annotations

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path


def load_conus_plan_module():
    path = (
        Path(__file__).resolve().parents[2] / "tools" / "hand" / "conus_build_plan.py"
    )
    spec = importlib.util.spec_from_file_location("conus_build_plan", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_conus_build_plan_emits_two_region_terrain_manifest():
    module = load_conus_plan_module()
    args = Namespace(
        dataset_version="hand-test",
        regions=["birmingham-prototype", "houston-bayou-pilot"],
        min_precompute_zoom=9,
        max_precompute_zoom=12,
        max_dynamic_zoom=14,
        cache_budget_gb=100,
    )

    plan = module.build_plan(args)
    manifest = plan["terrain_manifest"]
    jobs = plan["job_manifest"]

    assert manifest["dataset_version"] == "hand-test"
    regions = manifest["layers"]["hand"]["regions"]
    assert [region["id"] for region in regions] == [
        "birmingham-prototype",
        "houston-bayou-pilot",
    ]
    assert (
        jobs["mosaic_rule"]["cache_key"]
        == "{layer}/{dataset_version}/{z}/{x}/{y}.u16.br"
    )
    assert jobs["regions"][0]["serving"]["sample_note"].startswith("Cache-backed")


def test_conus_build_plan_writes_dry_run_outputs(tmp_path):
    module = load_conus_plan_module()
    args = Namespace(
        dataset_version="hand-test",
        regions=["birmingham-prototype", "houston-bayou-pilot"],
        min_precompute_zoom=9,
        max_precompute_zoom=12,
        max_dynamic_zoom=14,
        cache_budget_gb=100,
    )
    plan = module.build_plan(args)

    written = module.write_plan(tmp_path, plan)

    terrain_path = Path(written["terrain_manifest"])
    jobs_path = Path(written["job_manifest"])
    assert terrain_path.exists()
    assert jobs_path.exists()
    assert "houston-bayou-pilot" in terrain_path.read_text(encoding="utf-8")
    assert "download_verify_inputs" in jobs_path.read_text(encoding="utf-8")
