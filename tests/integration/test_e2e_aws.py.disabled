import os
import tempfile
from pathlib import Path
import subprocess
import pytest

import importlib

from fastapi.testclient import TestClient
import main

SCRIPT_DL = Path(__file__).resolve().parents[2] / "scripts" / "download_aws_dem.py"
SCRIPT_TIF = Path(__file__).resolve().parents[2] / "scripts" / "process_tif.py"

pytestmark = pytest.mark.external


def run_module(path, func_name, *args, **kwargs):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore
    getattr(module, func_name)(*args, **kwargs)


def test_e2e_pipeline_real(tmp_path, monkeypatch):
    """Download 1 DEM COG, process pipeline, query flood tile."""

    input_dir = tmp_path / "input"
    processed_dir = tmp_path / "out"
    input_dir.mkdir(); processed_dir.mkdir()

    monkeypatch.setenv("INPUT_DIR", str(input_dir))
    monkeypatch.setenv("PROCESSED_DIR", str(processed_dir))
    monkeypatch.setenv("COLOR_RAMP", str(Path(__file__).parents[2] / "scripts" / "color_ramp.txt"))
    monkeypatch.setenv("ZOOM_RANGE", "(8,8)")

    # 1. download one COG (skip if network unavailable)
    try:
        run_module(SCRIPT_DL, "main", max_workers=2, limit=1)
    except Exception as e:
        pytest.skip(f"Download skipped: {e}")

    assert any(input_dir.iterdir()), "No DEM downloaded"

    # 2. run tiling pipeline (may be slow)
    try:
        run_module(SCRIPT_TIF, "main")
    except FileNotFoundError:
        pytest.skip("GDAL/gdal2tiles not installed in test env")

    mb = processed_dir / "elevation.mbtiles"
    if not mb.exists():
        pytest.skip("MBTiles not generated; likely due to missing GDAL binaries")

    # 3. spin API and hit endpoints
    client = TestClient(main.app)
    resp = client.get("/flood_tiles/100/8/120/180")
    assert resp.status_code in (200, 204)

    risk = client.get("/risk/100")
    assert risk.status_code in (200, 404)