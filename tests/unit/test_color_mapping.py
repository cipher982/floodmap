"""
Unit tests for color_mapping.py - flood risk color conversion logic.
"""

import numpy as np
import pytest

# Import the module under test
from color_mapping import FloodRiskColorMapper


class TestFloodRiskColorMapper:
    """Test suite for FloodRiskColorMapper class."""

    @pytest.fixture
    def mapper(self):
        """Create a fresh mapper instance for each test."""
        return FloodRiskColorMapper()

    # ============== elevation_to_risk_level tests ==============

    def test_elevation_safe_zone(self, mapper):
        """Elevation 5m+ above water level should return risk 0.0 (safe)."""
        # Water at 0m, ground at 10m = 10m clearance
        assert mapper.elevation_to_risk_level(10.0, 0.0) == 0.0
        # Water at 5m, ground at 15m = 10m clearance
        assert mapper.elevation_to_risk_level(15.0, 5.0) == 0.0
        # Exactly at threshold (5m above water)
        assert mapper.elevation_to_risk_level(5.0, 0.0) == 0.0

    def test_elevation_caution_zone(self, mapper):
        """Elevation 2-5m above water level should return risk ~0.0-0.33."""
        # 4m above water = in caution zone
        risk = mapper.elevation_to_risk_level(4.0, 0.0)
        assert 0.0 < risk < 0.33

        # 3m above water = deeper in caution zone
        risk = mapper.elevation_to_risk_level(3.0, 0.0)
        assert 0.0 < risk < 0.33

        # 2m above water = edge of caution zone
        risk = mapper.elevation_to_risk_level(2.0, 0.0)
        assert abs(risk - 0.33) < 0.01  # Should be ~0.33

    def test_elevation_danger_zone(self, mapper):
        """Elevation 0.5-2m above water level should return risk ~0.33-0.66."""
        # 1m above water = in danger zone
        risk = mapper.elevation_to_risk_level(1.0, 0.0)
        assert 0.33 < risk < 0.66

        # 0.5m above water = edge of danger zone
        risk = mapper.elevation_to_risk_level(0.5, 0.0)
        assert abs(risk - 0.66) < 0.01  # Should be ~0.66

    def test_elevation_flooded_zone(self, mapper):
        """Elevation below 0.5m above water should return risk ~0.66-1.0."""
        # At water level
        risk = mapper.elevation_to_risk_level(0.0, 0.0)
        assert 0.66 < risk <= 1.0

        # Below water level
        risk = mapper.elevation_to_risk_level(-1.0, 0.0)
        assert risk == 1.0

        # Deep underwater
        risk = mapper.elevation_to_risk_level(-10.0, 5.0)
        assert risk == 1.0

    def test_elevation_risk_monotonic(self, mapper):
        """Risk should increase monotonically as elevation decreases."""
        water_level = 5.0
        elevations = [15.0, 10.0, 7.0, 6.0, 5.5, 5.0, 4.0, 3.0]
        risks = [mapper.elevation_to_risk_level(e, water_level) for e in elevations]

        for i in range(len(risks) - 1):
            assert risks[i] <= risks[i + 1], (
                f"Risk should be monotonic: {risks[i]} <= {risks[i + 1]} "
                f"for elevations {elevations[i]} -> {elevations[i + 1]}"
            )

    # ============== risk_to_color tests ==============

    def test_risk_to_color_safe(self, mapper):
        """Risk 0.0 should return safe color (green)."""
        color = mapper.risk_to_color(0.0)
        assert color == mapper.SAFE_COLOR

    def test_risk_to_color_flooded(self, mapper):
        """Risk 1.0 should return flooded color (blue)."""
        color = mapper.risk_to_color(1.0)
        # Allow small rounding differences from color blending
        for i in range(4):
            assert abs(color[i] - mapper.FLOODED_COLOR[i]) <= 1

    def test_risk_to_color_returns_rgba(self, mapper):
        """Color should always be a 4-tuple of ints 0-255."""
        for risk in [0.0, 0.25, 0.5, 0.75, 1.0]:
            color = mapper.risk_to_color(risk)
            assert len(color) == 4
            for channel in color:
                assert isinstance(channel, int)
                assert 0 <= channel <= 255

    def test_risk_to_color_transitions(self, mapper):
        """Test color transitions at zone boundaries."""
        # At 0.33, should be close to CAUTION_COLOR
        color_at_33 = mapper.risk_to_color(0.33)
        # Should be very close to caution yellow
        assert abs(color_at_33[0] - mapper.CAUTION_COLOR[0]) < 5

        # At 0.66, should be close to DANGER_COLOR
        color_at_66 = mapper.risk_to_color(0.66)
        assert abs(color_at_66[0] - mapper.DANGER_COLOR[0]) < 5

    # ============== _blend_colors tests ==============

    def test_blend_colors_at_zero(self, mapper):
        """t=0 should return first color unchanged."""
        color1 = (100, 150, 200, 255)
        color2 = (0, 0, 0, 0)
        result = mapper._blend_colors(color1, color2, 0.0)
        assert result == color1

    def test_blend_colors_at_one(self, mapper):
        """t=1 should return second color unchanged."""
        color1 = (100, 150, 200, 255)
        color2 = (0, 50, 100, 128)
        result = mapper._blend_colors(color1, color2, 1.0)
        assert result == color2

    def test_blend_colors_midpoint(self, mapper):
        """t=0.5 should return average of both colors."""
        color1 = (0, 0, 0, 0)
        color2 = (100, 100, 100, 100)
        result = mapper._blend_colors(color1, color2, 0.5)
        assert result == (50, 50, 50, 50)

    # ============== elevation_array_to_rgba tests ==============

    def test_array_to_rgba_shape(self, mapper):
        """Output array should have correct shape (H, W, 4)."""
        elevation = np.array([[0.0, 5.0], [10.0, 15.0]])
        result = mapper.elevation_array_to_rgba(elevation, water_level=0.0)
        assert result.shape == (2, 2, 4)

    def test_array_to_rgba_dtype(self, mapper):
        """Output array should be uint8."""
        elevation = np.array([[0.0, 5.0], [10.0, 15.0]])
        result = mapper.elevation_array_to_rgba(elevation, water_level=0.0)
        assert result.dtype == np.uint8

    def test_array_to_rgba_safe_elevation(self, mapper):
        """High elevation should produce safe (green) color."""
        elevation = np.array([[100.0]])  # Very high
        result = mapper.elevation_array_to_rgba(elevation, water_level=0.0)
        expected = np.array(mapper.SAFE_COLOR)
        np.testing.assert_array_equal(result[0, 0], expected)

    def test_array_to_rgba_flooded(self, mapper):
        """Underwater elevation should produce flooded (blue) color."""
        elevation = np.array([[-5.0]])  # Below water
        result = mapper.elevation_array_to_rgba(elevation, water_level=0.0)
        expected = np.array(mapper.FLOODED_COLOR)
        np.testing.assert_array_equal(result[0, 0], expected)

    def test_array_to_rgba_no_data_handling(self, mapper):
        """No-data values should be treated as sea level."""
        no_data = -32768
        elevation = np.array([[no_data, 10.0]])
        result = mapper.elevation_array_to_rgba(
            elevation, water_level=0.0, no_data_value=no_data
        )
        # No-data becomes 0m elevation, which is flooded at water_level=0
        assert result[0, 0, 3] > 0  # Should not be transparent

    def test_array_to_rgba_water_level_effect(self, mapper):
        """Different water levels should produce different colors for same elevation."""
        elevation = np.array([[5.0]])

        # Low water - should be safe (green)
        result_low = mapper.elevation_array_to_rgba(elevation, water_level=0.0)

        # High water - should be flooded (blue)
        result_high = mapper.elevation_array_to_rgba(elevation, water_level=10.0)

        # Colors should be different
        assert not np.array_equal(result_low, result_high)

    # ============== elevation_array_to_topographical_rgba tests ==============

    def test_topographical_shape(self, mapper):
        """Topographical output should have correct shape."""
        elevation = np.array([[0.0, 100.0], [500.0, 1500.0]])
        result = mapper.elevation_array_to_topographical_rgba(elevation)
        assert result.shape == (2, 2, 4)

    def test_topographical_dtype(self, mapper):
        """Topographical output should be uint8."""
        elevation = np.array([[0.0, 100.0]])
        result = mapper.elevation_array_to_topographical_rgba(elevation)
        assert result.dtype == np.uint8

    def test_topographical_low_elevation(self, mapper):
        """Very low elevation should be blue."""
        elevation = np.array([[2.0]])  # 0-5m band
        result = mapper.elevation_array_to_topographical_rgba(elevation)
        expected = np.array(mapper.ELEVATION_COLORS[0])
        np.testing.assert_array_equal(result[0, 0], expected)

    def test_topographical_high_elevation(self, mapper):
        """Very high elevation should be gray."""
        elevation = np.array([[5000.0]])  # Above 3000m
        result = mapper.elevation_array_to_topographical_rgba(elevation)
        expected = np.array(mapper.ELEVATION_COLORS[-1])
        np.testing.assert_array_equal(result[0, 0], expected)

    # ============== get_legend_colors tests ==============

    def test_legend_colors_structure(self, mapper):
        """Legend should return dict with expected keys."""
        legend = mapper.get_legend_colors(water_level=2.0)
        assert isinstance(legend, dict)
        assert len(legend) == 4  # Safe, Caution, Danger, Flooded

    def test_legend_colors_water_level_in_labels(self, mapper):
        """Legend labels should reflect current water level."""
        water_level = 5.0
        legend = mapper.get_legend_colors(water_level)

        # Check that labels contain water-level-adjusted thresholds
        keys = list(legend.keys())
        assert any("10.0" in k for k in keys)  # safe threshold = 5 + 5 = 10
        assert any("7.0" in k for k in keys)  # caution threshold = 5 + 2 = 7
        assert any("5.5" in k for k in keys)  # danger threshold = 5 + 0.5 = 5.5


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.fixture
    def mapper(self):
        return FloodRiskColorMapper()

    def test_negative_water_level(self, mapper):
        """Negative water levels should work (below sea level scenarios)."""
        # Ground at 0m, water at -5m = 5m clearance (safe)
        risk = mapper.elevation_to_risk_level(0.0, -5.0)
        assert risk == 0.0

    def test_extreme_elevation(self, mapper):
        """Very high elevations should still work."""
        risk = mapper.elevation_to_risk_level(8848.0, 0.0)  # Everest
        assert risk == 0.0

    def test_extreme_water_level(self, mapper):
        """Very high water levels should still work."""
        risk = mapper.elevation_to_risk_level(0.0, 1000.0)  # 1km flood
        assert risk == 1.0

    def test_large_array(self, mapper):
        """Should handle large arrays efficiently."""
        elevation = np.random.uniform(-10, 100, (1000, 1000))
        result = mapper.elevation_array_to_rgba(elevation, water_level=5.0)
        assert result.shape == (1000, 1000, 4)

    def test_single_pixel_array(self, mapper):
        """Should handle 1x1 arrays."""
        elevation = np.array([[5.0]])
        result = mapper.elevation_array_to_rgba(elevation, water_level=0.0)
        assert result.shape == (1, 1, 4)
