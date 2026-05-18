import zipfile
from pathlib import Path

from tools.hand.extract_ornl_elevation_sources import (
    extract_one,
    plan_extractions,
)
from tools.hand.ornl_source_inventory import SourceZipEntry


def test_plan_extractions_skips_existing_outputs(tmp_path: Path):
    huc = "031601"
    archive = tmp_path / f"{huc}.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(f"{huc}/{huc}.tif", b"elevation")
    output = (
        tmp_path / "hand-precomputed" / "ornl-cfim-v0.21" / huc / f"{huc}-elevation.tif"
    )
    output.parent.mkdir(parents=True)
    output.write_bytes(b"exists")

    planned, missing = plan_extractions(
        archives={
            huc: SourceZipEntry(
                huc=huc,
                path=str(archive),
                bytes=archive.stat().st_size,
                valid_name=True,
            )
        },
        data_root=tmp_path,
        hucs=[huc],
        start_after=None,
        limit=None,
        force=False,
    )

    assert planned == []
    assert missing == []


def test_extract_one_writes_elevation_member_atomically(tmp_path: Path):
    huc = "031601"
    archive = tmp_path / f"{huc}.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(f"{huc}/{huc}.tif", b"elevation-bytes")
    entry = SourceZipEntry(
        huc=huc,
        path=str(archive),
        bytes=archive.stat().st_size,
        valid_name=True,
    )
    planned, _ = plan_extractions(
        archives={huc: entry},
        data_root=tmp_path,
        hucs=[huc],
        start_after=None,
        limit=None,
        force=False,
    )

    result = extract_one(planned[0], progress_jsonl=None)
    output = Path(result["output"])

    assert output.read_bytes() == b"elevation-bytes"
    assert result["output_bytes"] == len(b"elevation-bytes")
    assert not output.with_suffix(output.suffix + ".tmp").exists()
