from __future__ import annotations

from tools.hand.ornl_source_inventory import (
    format_text,
    huc_from_zip_name,
    iter_source_zip_entries,
    summarize_inventory,
)


def test_huc_from_zip_name_accepts_six_digit_huc(tmp_path) -> None:
    assert huc_from_zip_name(tmp_path / "031601.zip") == "031601"
    assert huc_from_zip_name(tmp_path / "31601.zip") is None
    assert huc_from_zip_name(tmp_path / "031601.tif") is None


def test_inventory_summarizes_split_roots_and_duplicates(tmp_path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    (root_a / "031601.zip").write_bytes(b"a" * 10)
    (root_a / "bad-name.zip").write_bytes(b"bad")
    (root_b / "031601.zip").write_bytes(b"duplicate")
    (root_b / "010700.zip").write_bytes(b"merrimack")

    entries = iter_source_zip_entries((root_a, root_b))
    summary = summarize_inventory(
        entries,
        roots=(root_a, root_b),
        expected_count=331,
        expected_bytes=100,
    )

    assert summary["zip_count"] == 4
    assert summary["valid_huc_count"] == 2
    assert summary["bytes_downloaded"] == 31
    assert summary["remaining_count"] == 329
    assert summary["remaining_bytes_estimate"] == 69
    assert list(summary["duplicate_hucs"]) == ["031601"]
    assert summary["invalid_entries"][0]["path"].endswith("bad-name.zip")


def test_format_text_reports_progress(tmp_path) -> None:
    summary = summarize_inventory(
        [],
        roots=(tmp_path / "missing",),
        expected_count=331,
        expected_bytes=100,
    )

    text = format_text(summary)

    assert "ZIP files: 0" in text
    assert "Count progress: 0/331" in text
    assert "Byte progress: 0/100" in text
