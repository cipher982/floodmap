#!/usr/bin/env python3
"""
End-to-end validation: coordinate → elevation → final pixel color.
This will NOT STOP until every discrepancy is found and fixed.
"""

import sys
import os
sys.path.append('/Users/davidrose/git/floodmap/src')

import requests
import numpy as np
from PIL import Image
import io
import json
import random
import time

# Import the actual server components
from api.elevation_loader import elevation_loader
from api.color_mapping import color_mapper

class EndToEndValidator:
    """Validates the entire pipeline from coordinates to final pixel colors."""
    
    def __init__(self):
        self.server_base = "http://localhost:8000"
        self.failures = []
        self.tests_run = 0
        self.tests_passed = 0
        
    def log_failure(self, test_name, details):
        """Log a failure with full details."""
        self.failures.append(f"FAILURE: {test_name}\n{details}\n" + "="*60)
        print(f"❌ FAILED: {test_name}")
        print(f"   {details}")
    
    def log_success(self, test_name):
        """Log a successful test."""
        self.tests_passed += 1
        print(f"✅ PASSED: {test_name}")
    
    def test_coordinate_to_elevation_api(self, lat, lon):
        """Test the point-click elevation API."""
        try:
            response = requests.post(
                f"{self.server_base}/api/risk/location",
                json={"latitude": lat, "longitude": lon},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("elevation_m")
            else:
                return None
        except Exception as e:
            return None
    
    def test_coordinate_to_tile_pixel(self, lat, lon, water_level):
        """Get the actual pixel value from the tile overlay at a coordinate."""
        try:
            # Convert lat/lon to tile coordinates at zoom 8 (typical map zoom)
            zoom = 8
            x, y = elevation_loader.deg2num(lat, lon, zoom)
            
            # Get the tile that contains this coordinate
            tile_response = requests.get(
                f"{self.server_base}/api/tiles/elevation/{water_level}/{zoom}/{x}/{y}.png",
                timeout=10
            )
            
            if tile_response.status_code != 200:
                return None, None, None
                
            # Load the tile image
            tile_img = Image.open(io.BytesIO(tile_response.content))
            tile_array = np.array(tile_img)
            
            # Convert lat/lon to pixel within the tile
            lat_top, lat_bottom, lon_left, lon_right = elevation_loader.num2deg(x, y, zoom)
            
            # Calculate pixel position within 256x256 tile
            pixel_x = int((lon - lon_left) / (lon_right - lon_left) * 256)
            pixel_y = int((lat_top - lat) / (lat_top - lat_bottom) * 256)
            
            # Clamp to tile bounds
            pixel_x = max(0, min(255, pixel_x))
            pixel_y = max(0, min(255, pixel_y))
            
            # Get the actual pixel color
            if len(tile_array.shape) == 3 and tile_array.shape[2] >= 3:
                pixel_color = tile_array[pixel_y, pixel_x, :3]  # RGB
                return pixel_color, (pixel_x, pixel_y), (x, y)
            else:
                return None, None, None
                
        except Exception as e:
            return None, None, None
    
    def get_elevation_from_pixel_color(self, pixel_color, water_level):
        """Reverse-engineer what elevation would produce this pixel color."""
        # Try elevation values from -10m to 100m
        for test_elevation in range(-10, 101):
            test_rgba = color_mapper.elevation_array_to_rgba(
                np.array([[test_elevation]], dtype=np.int16), 
                water_level
            )
            test_color = test_rgba[0, 0, :3]  # RGB only
            
            # Check if colors match (allow some tolerance)
            if np.allclose(pixel_color, test_color, atol=5):
                return test_elevation
        
        return None
    
    def test_single_coordinate(self, lat, lon, water_level=3.6):
        """Complete end-to-end test for a single coordinate."""
        self.tests_run += 1
        test_name = f"Coordinate ({lat:.4f}, {lon:.4f})"
        
        print(f"\n🔍 Testing {test_name}")
        
        # Step 1: Get elevation from point-click API
        api_elevation = self.test_coordinate_to_elevation_api(lat, lon)
        if api_elevation is None:
            self.log_failure(test_name, "Point-click API failed or returned null elevation")
            return False
        
        print(f"   Point-click API elevation: {api_elevation:.1f}m")
        
        # Step 2: Get pixel color from tile overlay
        pixel_color, pixel_pos, tile_coords = self.test_coordinate_to_tile_pixel(lat, lon, water_level)
        if pixel_color is None:
            self.log_failure(test_name, "Failed to get pixel from tile overlay")
            return False
        
        print(f"   Tile pixel color: RGB{tuple(pixel_color)} at pixel {pixel_pos} in tile {tile_coords}")
        
        # Step 3: Reverse-engineer what elevation this pixel represents
        inferred_elevation = self.get_elevation_from_pixel_color(pixel_color, water_level)
        if inferred_elevation is None:
            self.log_failure(test_name, f"Could not determine elevation for pixel color RGB{tuple(pixel_color)}")
            return False
        
        print(f"   Inferred elevation from pixel: {inferred_elevation}m")
        
        # Step 4: Compare API elevation vs pixel-inferred elevation
        elevation_diff = abs(api_elevation - inferred_elevation)
        tolerance = 5.0  # 5 meter tolerance
        
        if elevation_diff <= tolerance:
            self.log_success(test_name)
            return True
        else:
            self.log_failure(
                test_name, 
                f"ELEVATION MISMATCH:\n"
                f"   Point-click API: {api_elevation:.1f}m\n"
                f"   Tile pixel shows: {inferred_elevation}m\n"
                f"   Difference: {elevation_diff:.1f}m (tolerance: {tolerance}m)\n"
                f"   Pixel color: RGB{tuple(pixel_color)}\n"
                f"   Water level: {water_level}m"
            )
            return False
    
    def test_systematic_grid(self):
        """Test a systematic grid across problem areas."""
        print("\n🌊 Testing systematic grid across Tampa Bay area...")
        
        # Focus on Tampa Bay area where issues were reported
        lat_min, lat_max = 27.5, 29.5
        lon_min, lon_max = -85.0, -82.0
        
        grid_points = []
        for lat in np.arange(lat_min, lat_max, 0.1):  # Every 0.1 degrees
            for lon in np.arange(lon_min, lon_max, 0.1):
                grid_points.append((lat, lon))
        
        print(f"Testing {len(grid_points)} grid points...")
        
        failed_points = []
        for i, (lat, lon) in enumerate(grid_points):
            if i % 50 == 0:
                print(f"Progress: {i}/{len(grid_points)} ({100*i/len(grid_points):.1f}%)")
            
            success = self.test_single_coordinate(lat, lon)
            if not success:
                failed_points.append((lat, lon))
        
        if failed_points:
            print(f"\n🚨 GRID TEST FAILURES: {len(failed_points)}/{len(grid_points)} points failed")
            print("Failed coordinates:")
            for lat, lon in failed_points[:10]:  # Show first 10
                print(f"   ({lat:.4f}, {lon:.4f})")
            if len(failed_points) > 10:
                print(f"   ... and {len(failed_points) - 10} more")
        else:
            print(f"\n✅ GRID TEST SUCCESS: All {len(grid_points)} points passed!")
    
    def test_random_samples(self, num_samples=100):
        """Test random samples across the USA."""
        print(f"\n🎲 Testing {num_samples} random samples across USA...")
        
        # USA bounding box
        lat_min, lat_max = 25.0, 49.0
        lon_min, lon_max = -125.0, -66.0
        
        failed_samples = []
        for i in range(num_samples):
            lat = random.uniform(lat_min, lat_max)
            lon = random.uniform(lon_min, lon_max)
            
            if i % 20 == 0:
                print(f"Progress: {i}/{num_samples} ({100*i/num_samples:.1f}%)")
            
            success = self.test_single_coordinate(lat, lon)
            if not success:
                failed_samples.append((lat, lon))
        
        if failed_samples:
            print(f"\n🚨 RANDOM TEST FAILURES: {len(failed_samples)}/{num_samples} samples failed")
        else:
            print(f"\n✅ RANDOM TEST SUCCESS: All {num_samples} samples passed!")
    
    def test_known_problem_areas(self):
        """Test specific coordinates that were known to be problematic."""
        print("\n🎯 Testing known problem coordinates...")
        
        problem_coords = [
            (28.5, -83.5),   # Tampa area
            (28.8, -82.9),   # Tampa Bay
            (29.1, -83.2),   # North of Tampa
            (27.9, -82.4),   # South Tampa
            (28.3, -84.0),   # Gulf side
        ]
        
        for lat, lon in problem_coords:
            self.test_single_coordinate(lat, lon)
    
    def run_comprehensive_test(self):
        """Run the complete validation suite."""
        print("🚀 COMPREHENSIVE END-TO-END VALIDATION")
        print("=" * 60)
        print("This will NOT STOP until every discrepancy is found.")
        print()
        
        start_time = time.time()
        
        # Test 1: Known problem areas
        self.test_known_problem_areas()
        
        # Test 2: Random samples
        self.test_random_samples(50)  # Start with 50 samples
        
        # Test 3: Systematic grid (if needed)
        if self.failures:
            print("\n⚠️  Failures detected, running systematic grid test...")
            self.test_systematic_grid()
        
        # Final report
        elapsed = time.time() - start_time
        print("\n" + "=" * 60)
        print("🏁 FINAL VALIDATION REPORT")
        print("=" * 60)
        print(f"Tests run: {self.tests_run}")
        print(f"Tests passed: {self.tests_passed}")
        print(f"Tests failed: {len(self.failures)}")
        print(f"Success rate: {100 * self.tests_passed / self.tests_run:.1f}%")
        print(f"Time elapsed: {elapsed:.1f} seconds")
        
        if self.failures:
            print(f"\n🚨 {len(self.failures)} FAILURES DETECTED:")
            for failure in self.failures:
                print(failure)
            print("\n❌ VALIDATION FAILED - System is broken and needs fixes")
            return False
        else:
            print("\n✅ VALIDATION PASSED - System is working correctly")
            return True

def main():
    """Run the comprehensive validation."""
    validator = EndToEndValidator()
    
    # Check server is running
    try:
        response = requests.get(f"{validator.server_base}/api/tiles/elevation/3.6/8/68/106.png", timeout=5)
        if response.status_code == 200:
            print("✅ Server is responding")
        else:
            print(f"⚠️  Server returned status {response.status_code}")
    except Exception as e:
        print(f"❌ Cannot connect to server: {e}")
        print("Start the server first: cd src/api && uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload")
        return
    
    success = validator.run_comprehensive_test()
    
    if not success:
        print("\n🔧 NEXT STEPS:")
        print("1. Fix the identified discrepancies")
        print("2. Re-run this validator")
        print("3. Repeat until 100% success rate")
        sys.exit(1)
    else:
        print("\n🎉 System is working correctly!")
        sys.exit(0)

if __name__ == "__main__":
    main()