#!/usr/bin/env python3
"""
Debug tests for MapLibre tile URL generation issues.
This test helps identify and fix the "/null/tiles/" URL problem.
"""
import pytest
import re
from main import generate_maplibre_html


class TestMapLibreTileUrls:
    """Debug MapLibre tile URL generation."""
    
    def test_maplibre_html_generation(self):
        """Test that MapLibre HTML generates correct tile URLs."""
        latitude = 27.9506
        longitude = -82.4585
        elevation = 15.0
        water_level = 10.0
        
        html = generate_maplibre_html(latitude, longitude, elevation, water_level)
        
        # Debug: Print the generated HTML to see what's wrong
        print("\n=== GENERATED HTML ===")
        print(html)
        print("=== END HTML ===\n")
        
        # Check that the HTML doesn't contain "/null/" paths
        assert "/null/" not in html, "HTML contains '/null/' paths - URL template not working"
        
        # Check for correct tile URL patterns
        vector_tile_pattern = r"'/vector_tiles/\{z\}/\{x\}/\{y\}\.pbf'"
        elevation_tile_pattern = r"'/tiles/\{z\}/\{x\}/\{y\}'"
        flood_tile_pattern = rf"'/flood_tiles/{water_level}/\{{z\}}/\{{x\}}/\{{y\}}'"
        
        assert re.search(vector_tile_pattern, html), "Vector tile URL pattern not found"
        assert re.search(elevation_tile_pattern, html), "Elevation tile URL pattern not found"
        assert re.search(flood_tile_pattern, html), "Flood tile URL pattern not found"
        
        # Check coordinate substitution worked
        assert str(latitude) in html, "Latitude not substituted correctly"
        assert str(longitude) in html, "Longitude not substituted correctly"
        
    def test_string_concatenation_vs_fstring(self):
        """Test different approaches to HTML generation."""
        
        # Test values
        lat, lon, elev, water = 27.9506, -82.4585, 15.0, 10.0
        
        # Method 1: f-string with escaped braces (current - broken)
        fstring_approach = f"""
        tiles: [window.location.origin + '/tiles/{{z}}/{{x}}/{{y}}']
        center: [{lon}, {lat}]
        """
        
        # Method 2: String concatenation (should work)
        concat_approach = """
        tiles: [window.location.origin + '/tiles/{z}/{x}/{y}']
        center: [""" + str(lon) + """, """ + str(lat) + """]
        """
        
        print(f"\nf-string approach: {fstring_approach}")
        print(f"concat approach: {concat_approach}")
        
        # The f-string approach creates literal braces, not template placeholders
        assert "{{z}}" in fstring_approach, "f-string creates literal braces"
        assert "{z}" in concat_approach, "concat preserves template placeholders"
        
    def test_corrected_maplibre_function(self):
        """Test a corrected version of the MapLibre function."""
        
        def generate_maplibre_html_fixed(latitude, longitude, elevation, water_level):
            """Fixed version using proper string templating."""
            return f"""
            <script>
                const map = new maplibregl.Map({{
                    container: 'map',
                    style: {{
                        sources: {{
                            'osm': {{
                                type: 'vector',
                                tiles: [window.location.origin + '/vector_tiles/{{z}}/{{x}}/{{y}}.pbf']
                            }}
                        }}
                    }},
                    center: [{longitude}, {latitude}]
                }});
            </script>
            """.replace("{{", "{").replace("}}", "}")
            
        html = generate_maplibre_html_fixed(27.9506, -82.4585, 15.0, 10.0)
        
        # Should have correct tile URL pattern
        assert "/vector_tiles/{z}/{x}/{y}.pbf" in html
        assert "/null/" not in html
        
        print(f"\nFixed HTML: {html}")


if __name__ == "__main__":
    # Run debug tests directly
    test = TestMapLibreTileUrls()
    print("🔍 Running MapLibre URL debug tests...")
    
    try:
        test.test_maplibre_html_generation()
        print("✅ HTML generation test passed")
    except AssertionError as e:
        print(f"❌ HTML generation test failed: {e}")
    
    try:
        test.test_string_concatenation_vs_fstring()
        print("✅ String method comparison passed")
    except AssertionError as e:
        print(f"❌ String method comparison failed: {e}")
        
    try:
        test.test_corrected_maplibre_function()
        print("✅ Corrected function test passed")
    except AssertionError as e:
        print(f"❌ Corrected function test failed: {e}")