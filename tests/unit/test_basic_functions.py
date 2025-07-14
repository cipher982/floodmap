"""Basic unit tests for core functions."""
import pytest
import math


@pytest.mark.unit
class TestCoordinateConversion:
    """Test coordinate conversion functions."""
    
    def test_lat_lon_to_tile_basic(self):
        """Test basic lat/lon to tile conversion."""
        # Import here to avoid module loading issues
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        
        from main import lat_lon_to_tile
        
        # Tampa coordinates at zoom 10
        lat, lon = 27.9506, -82.4585
        zoom = 10
        
        x, y = lat_lon_to_tile(lat, lon, zoom)
        
        # Basic sanity checks
        assert isinstance(x, int)
        assert isinstance(y, int)
        assert 0 <= x < (2 ** zoom)
        assert 0 <= y < (2 ** zoom)
        
        # Tampa should be roughly around these tiles at zoom 10
        assert 270 <= x <= 280  # Rough range for Tampa longitude
        assert 420 <= y <= 430  # Rough range for Tampa latitude
    
    def test_tile_to_lat_lon_basic(self):
        """Test basic tile to lat/lon conversion."""
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        
        from main import tile_to_lat_lon
        
        # Test tile coordinates
        x, y, zoom = 275, 427, 10
        
        lat, lon = tile_to_lat_lon(x, y, zoom)
        
        # Should return valid coordinates
        assert isinstance(lat, float)
        assert isinstance(lon, float)
        assert -90 <= lat <= 90
        assert -180 <= lon <= 180
        
        # Should be in Tampa area
        assert 25 <= lat <= 30  # Florida latitude range
        assert -85 <= lon <= -80  # Florida longitude range

    def test_coordinate_conversion_roundtrip(self):
        """Test that coordinate conversions are reversible."""
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        
        from main import lat_lon_to_tile, tile_to_lat_lon
        
        # Original coordinates
        orig_lat, orig_lon = 27.9506, -82.4585
        zoom = 12
        
        # Convert to tile
        x, y = lat_lon_to_tile(orig_lat, orig_lon, zoom)
        
        # Convert back to coordinates
        new_lat, new_lon = tile_to_lat_lon(x, y, zoom)
        
        # Should be close (within tile precision)
        lat_diff = abs(orig_lat - new_lat)
        lon_diff = abs(orig_lon - new_lon)
        
        # Tolerance depends on zoom level
        tolerance = 1.0 / (2 ** zoom) * 360  # Rough tile size in degrees
        
        assert lat_diff < tolerance
        assert lon_diff < tolerance


@pytest.mark.unit
class TestTileValidation:
    """Test tile coordinate validation."""
    
    def test_valid_tile_coordinates(self):
        """Test validation of valid tile coordinates."""
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        
        from main import _validate_tile_coordinates
        
        # Valid coordinates
        valid_coords = [
            (0, 0, 0),      # World tile
            (10, 512, 512), # Mid-zoom tile
            (18, 50000, 50000),  # High-zoom tile
        ]
        
        for z, x, y in valid_coords:
            assert _validate_tile_coordinates(z, x, y), f"Should be valid: {z}/{x}/{y}"
    
    def test_invalid_tile_coordinates(self):
        """Test validation of invalid tile coordinates."""
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        
        from main import _validate_tile_coordinates
        
        # Invalid coordinates
        invalid_coords = [
            (-1, 0, 0),     # Negative zoom
            (0, -1, 0),     # Negative X
            (0, 0, -1),     # Negative Y
            (30, 0, 0),     # Zoom too high
            (10, 2000, 0),  # X too high for zoom
            (10, 0, 2000),  # Y too high for zoom
        ]
        
        for z, x, y in invalid_coords:
            assert not _validate_tile_coordinates(z, x, y), f"Should be invalid: {z}/{x}/{y}"


@pytest.mark.unit
class TestColorGeneration:
    """Test color generation utilities."""
    
    def test_get_color_basic(self):
        """Test basic color generation."""
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        
        from main import get_color
        
        # Test extreme values
        color_min = get_color(-1.0)
        color_max = get_color(1.0)
        color_mid = get_color(0.0)
        
        # Should return RGB strings
        assert color_min.startswith("rgb(")
        assert color_max.startswith("rgb(")
        assert color_mid.startswith("rgb(")
        
        # Should be different colors
        assert color_min != color_max
        
        # Should contain valid RGB values
        import re
        rgb_pattern = r"rgb\((\d+), (\d+), (\d+)\)"
        
        for color in [color_min, color_max, color_mid]:
            match = re.match(rgb_pattern, color)
            assert match, f"Invalid RGB format: {color}"
            
            r, g, b = map(int, match.groups())
            assert 0 <= r <= 255
            assert 0 <= g <= 255  
            assert 0 <= b <= 255