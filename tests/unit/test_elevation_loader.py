"""
Unit tests for elevation_loader.py - coordinate conversion and tile math.

These tests cover the pure functions that don't require external data files.
"""

from pathlib import Path

import pytest

# Import the module under test
from elevation_loader import ElevationDataLoader


class TestDeg2Num:
    """Test lat/lon to tile coordinate conversion (Web Mercator)."""

    @pytest.fixture
    def loader(self):
        """Create loader with mocked data directory."""
        return ElevationDataLoader(data_dir=Path("/fake/data"))

    # ============== Known Reference Points ==============

    def test_origin_zoom_0(self, loader):
        """At zoom 0, the entire world is one tile (0, 0)."""
        x, y = loader.deg2num(0, 0, 0)
        assert x == 0
        assert y == 0

    def test_origin_zoom_1(self, loader):
        """At zoom 1, origin (0,0) is at tile (1, 1)."""
        x, y = loader.deg2num(0, 0, 1)
        assert x == 1
        assert y == 1

    def test_new_york_city(self, loader):
        """Test known tile coordinates for NYC (40.7128, -74.0060)."""
        # At zoom 10, NYC should be around tile (301, 384-385)
        x, y = loader.deg2num(40.7128, -74.0060, 10)
        assert x == 301
        assert y in [384, 385]  # Allow for coordinate precision

    def test_tampa_florida(self, loader):
        """Test known tile coordinates for Tampa (27.9506, -82.4572)."""
        # At zoom 10, Tampa should be around tile (277, 429)
        x, y = loader.deg2num(27.9506, -82.4572, 10)
        assert x == 277
        assert y == 429

    def test_miami_florida(self, loader):
        """Test known tile coordinates for Miami (25.7617, -80.1918)."""
        # At zoom 10, Miami area - verify reasonable bounds
        x, y = loader.deg2num(25.7617, -80.1918, 10)
        # Miami is in southern Florida, should be reasonable tile coords
        # x should be around 280-285 (longitude ~-80)
        # y should be around 430-450 (latitude ~26)
        assert 275 <= x <= 290
        assert 430 <= y <= 455

    # ============== Edge Cases ==============

    def test_max_longitude_west(self, loader):
        """Longitude -180 should map to x=0."""
        x, _ = loader.deg2num(0, -180, 10)
        assert x == 0

    def test_max_longitude_east(self, loader):
        """Longitude approaching 180 should map to max x."""
        x, _ = loader.deg2num(0, 179.999, 10)
        assert x == 1023  # 2^10 - 1

    def test_high_latitude_north(self, loader):
        """High northern latitude should still produce valid tile."""
        x, y = loader.deg2num(85.0, 0, 10)
        assert 0 <= x < 1024
        assert y == 0 or y > 0  # Should be near top

    def test_high_latitude_south(self, loader):
        """High southern latitude should still produce valid tile."""
        x, y = loader.deg2num(-85.0, 0, 10)
        assert 0 <= x < 1024
        assert y < 1024  # Should be near bottom

    # ============== Zoom Level Behavior ==============

    def test_zoom_doubles_tiles(self, loader):
        """Each zoom level should double the number of tiles."""
        lat, lon = 40.0, -74.0

        x10, y10 = loader.deg2num(lat, lon, 10)
        x11, y11 = loader.deg2num(lat, lon, 11)
        x12, y12 = loader.deg2num(lat, lon, 12)

        # Each zoom level doubles the coordinates
        assert x11 in [x10 * 2, x10 * 2 + 1]
        assert y11 in [y10 * 2, y10 * 2 + 1]
        assert x12 in [x11 * 2, x11 * 2 + 1]
        assert y12 in [y11 * 2, y11 * 2 + 1]

    def test_zoom_0_single_tile(self, loader):
        """At zoom 0, all coordinates should map to (0, 0)."""
        assert loader.deg2num(45.0, -90.0, 0) == (0, 0)
        assert loader.deg2num(-45.0, 90.0, 0) == (0, 0)


class TestNum2Deg:
    """Test tile coordinate to lat/lon bounds conversion."""

    @pytest.fixture
    def loader(self):
        return ElevationDataLoader(data_dir=Path("/fake/data"))

    # ============== Basic Structure ==============

    def test_returns_four_values(self, loader):
        """Should return (lat_top, lat_bottom, lon_left, lon_right)."""
        result = loader.num2deg(0, 0, 0)
        assert len(result) == 4

    def test_bounds_ordering(self, loader):
        """lat_top > lat_bottom, lon_right > lon_left."""
        lat_top, lat_bottom, lon_left, lon_right = loader.num2deg(100, 200, 10)
        assert lat_top > lat_bottom
        assert lon_right > lon_left

    # ============== Known Reference Points ==============

    def test_zoom_0_full_world(self, loader):
        """Zoom 0 tile (0,0) should cover the whole world."""
        lat_top, lat_bottom, lon_left, lon_right = loader.num2deg(0, 0, 0)

        assert lon_left == pytest.approx(-180.0, abs=0.01)
        assert lon_right == pytest.approx(180.0, abs=0.01)
        # Web Mercator only goes to ~85 degrees latitude
        assert lat_top > 80
        assert lat_bottom < -80

    def test_tile_width_at_equator(self, loader):
        """At zoom 10, tiles should be ~0.35 degrees wide."""
        lat_top, lat_bottom, lon_left, lon_right = loader.num2deg(512, 512, 10)
        width = lon_right - lon_left
        # 360 / 2^10 = 0.3515625
        assert width == pytest.approx(0.3515625, abs=0.001)

    # ============== Roundtrip Consistency ==============

    def test_roundtrip_conversion(self, loader):
        """deg2num and num2deg should be inverse operations."""
        lat, lon = 40.7128, -74.0060  # NYC
        zoom = 12

        x, y = loader.deg2num(lat, lon, zoom)
        lat_top, lat_bottom, lon_left, lon_right = loader.num2deg(x, y, zoom)

        # Original point should be within the tile bounds
        assert lat_bottom <= lat <= lat_top
        assert lon_left <= lon <= lon_right

    def test_roundtrip_multiple_locations(self, loader):
        """Roundtrip should work for various locations."""
        locations = [
            (40.7128, -74.0060),  # NYC
            (27.9506, -82.4572),  # Tampa
            (25.7617, -80.1918),  # Miami
            (34.0522, -118.2437),  # LA
            (29.7604, -95.3698),  # Houston
        ]

        for lat, lon in locations:
            for zoom in [8, 10, 12, 14]:
                x, y = loader.deg2num(lat, lon, zoom)
                lat_top, lat_bottom, lon_left, lon_right = loader.num2deg(x, y, zoom)

                assert lat_bottom <= lat <= lat_top, (
                    f"Lat {lat} not in [{lat_bottom}, {lat_top}]"
                )
                assert lon_left <= lon <= lon_right, (
                    f"Lon {lon} not in [{lon_left}, {lon_right}]"
                )


class TestFindElevationFilesForTile:
    """Test elevation file lookup based on tile bounds."""

    @pytest.fixture
    def loader(self, tmp_path):
        """Create loader with a temporary data directory."""
        return ElevationDataLoader(data_dir=tmp_path)

    def test_filename_format_northern_hemisphere(self, loader, tmp_path):
        """Files in northern hemisphere should use 'n' prefix."""
        # Create test file for Tampa area (lat ~28, lon ~-82)
        test_file = tmp_path / "n27_w083_1arc_v3.zst"
        test_file.touch()

        files = loader.find_elevation_files_for_tile(
            lat_top=28.0, lat_bottom=27.5, lon_left=-83.0, lon_right=-82.5
        )

        assert len(files) == 1
        assert "n27_w083" in str(files[0])

    def test_filename_format_southern_hemisphere(self, loader, tmp_path):
        """Files in southern hemisphere should use 's' prefix."""
        # Create test file for southern location
        test_file = tmp_path / "s10_w050_1arc_v3.zst"
        test_file.touch()

        files = loader.find_elevation_files_for_tile(
            lat_top=-9.5, lat_bottom=-10.5, lon_left=-50.5, lon_right=-49.5
        )

        assert len(files) == 1
        assert "s10_w050" in str(files[0])

    def test_filename_format_eastern_hemisphere(self, loader, tmp_path):
        """Files in eastern hemisphere should use 'e' prefix."""
        test_file = tmp_path / "n40_e010_1arc_v3.zst"
        test_file.touch()

        files = loader.find_elevation_files_for_tile(
            lat_top=41.0, lat_bottom=40.5, lon_left=10.0, lon_right=10.5
        )

        assert len(files) == 1
        assert "n40_e010" in str(files[0])

    def test_multiple_files_spanning_boundary(self, loader, tmp_path):
        """Tiles spanning multiple degree squares should find multiple files."""
        # Create files for a 2x2 degree area around Tampa
        # Note: For latitude 27-28, files are n27, n28
        # For longitude -83 to -82 (west), files use w083, w082
        test_files = [
            "n27_w082_1arc_v3.zst",
            "n27_w083_1arc_v3.zst",
            "n28_w082_1arc_v3.zst",
            "n28_w083_1arc_v3.zst",
        ]
        for filename in test_files:
            (tmp_path / filename).touch()

        # Query a tile that spans the boundary
        files = loader.find_elevation_files_for_tile(
            lat_top=28.5, lat_bottom=27.5, lon_left=-83.5, lon_right=-82.5
        )

        assert len(files) >= 2  # Should find at least 2 overlapping files

    def test_no_files_found(self, loader, tmp_path):
        """Should return empty list when no files exist."""
        files = loader.find_elevation_files_for_tile(
            lat_top=28.0, lat_bottom=27.0, lon_left=-83.0, lon_right=-82.0
        )
        assert files == []

    def test_file_not_overlapping(self, loader, tmp_path):
        """Should not return files that don't overlap the tile bounds."""
        # Create file for different area
        test_file = tmp_path / "n40_w074_1arc_v3.zst"  # NYC area
        test_file.touch()

        # Query Tampa area
        files = loader.find_elevation_files_for_tile(
            lat_top=28.0, lat_bottom=27.0, lon_left=-83.0, lon_right=-82.0
        )

        assert files == []


class TestCoordinateMath:
    """Test mathematical properties of coordinate conversions."""

    @pytest.fixture
    def loader(self):
        return ElevationDataLoader(data_dir=Path("/fake/data"))

    def test_tiles_cover_earth_completely(self, loader):
        """Adjacent tiles should share edges with no gaps."""
        zoom = 10

        # Get bounds for two adjacent tiles
        bounds1 = loader.num2deg(500, 500, zoom)
        bounds2 = loader.num2deg(501, 500, zoom)

        # Right edge of tile 1 should equal left edge of tile 2
        lat_top1, lat_bottom1, lon_left1, lon_right1 = bounds1
        lat_top2, lat_bottom2, lon_left2, lon_right2 = bounds2

        assert lon_right1 == pytest.approx(lon_left2, abs=1e-10)
        assert lat_top1 == pytest.approx(lat_top2, abs=1e-10)
        assert lat_bottom1 == pytest.approx(lat_bottom2, abs=1e-10)

    def test_tiles_cover_vertically(self, loader):
        """Vertically adjacent tiles should share edges."""
        zoom = 10

        bounds1 = loader.num2deg(500, 500, zoom)
        bounds2 = loader.num2deg(500, 501, zoom)

        lat_top1, lat_bottom1, lon_left1, lon_right1 = bounds1
        lat_top2, lat_bottom2, lon_left2, lon_right2 = bounds2

        # Bottom of tile 1 should equal top of tile 2
        assert lat_bottom1 == pytest.approx(lat_top2, abs=1e-10)

    def test_parent_child_tile_relationship(self, loader):
        """Child tiles should be contained within parent tile."""
        parent_zoom = 10
        child_zoom = 11

        # Get parent tile
        parent_x, parent_y = 500, 500
        parent_bounds = loader.num2deg(parent_x, parent_y, parent_zoom)
        p_lat_top, p_lat_bottom, p_lon_left, p_lon_right = parent_bounds

        # Child tiles are at (2*x, 2*y), (2*x+1, 2*y), (2*x, 2*y+1), (2*x+1, 2*y+1)
        for dx in [0, 1]:
            for dy in [0, 1]:
                child_x = 2 * parent_x + dx
                child_y = 2 * parent_y + dy
                child_bounds = loader.num2deg(child_x, child_y, child_zoom)
                c_lat_top, c_lat_bottom, c_lon_left, c_lon_right = child_bounds

                # Child should be entirely within parent
                assert c_lat_top <= p_lat_top + 1e-10
                assert c_lat_bottom >= p_lat_bottom - 1e-10
                assert c_lon_left >= p_lon_left - 1e-10
                assert c_lon_right <= p_lon_right + 1e-10
