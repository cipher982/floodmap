"""Quick integrity checks for a handful of random SRTM *.zst tiles.

The purpose of this test is *not* to exhaustively validate every elevation
file (there are >2000 of them) but to give us an early warning when an obvious
corruption sneaks into the data-set – e.g. a file that decompresses to an all-
zero array, is filled with the NoData value, or exceeds the expected output
size.

Because the checks run as part of the normal pytest suite they must finish in
< a few seconds.  We therefore look at only 5 random tiles from the output
folder each time the suite is executed.
"""

from pathlib import Path

import pytest

from utils.elevation_validator import sample_elevation_files, validate_elevation_file

DATA_DIR = Path("output/elevation")


@pytest.mark.parametrize("file_path", sample_elevation_files(DATA_DIR, sample_size=5))
def test_basic_statistics(file_path: Path) -> None:
    """Ensure min != max and that the tile contains at least some non-zero data."""

    stats = validate_elevation_file(file_path)

    # The data set should not be completely homogeneous.
    assert stats["min"] != stats["max"], (
        f"{file_path.name} appears to have no elevation variation (min == max == {stats['min']})"
    )

    # Reject tiles that are 100 % zero – that would break the colour mapping.
    assert stats["zero_pct"] < 100.0, f"{file_path.name} is entirely zero-filled"

    # At least 80 % of the pixels should contain a *valid* (non-NoData) value.
    # Ocean tiles can legitimately be 0 m so we cannot test for that here.
    assert stats["nodata_pct"] < 20.0, (
        f"More than 20 % NoData pixels in {file_path.name} – looks suspicious"
    )
