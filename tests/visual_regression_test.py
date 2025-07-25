#!/usr/bin/env python3
"""
Automated visual regression testing for flood map tiles.
Ensures that changes don't break coordinate alignment or visual quality.
"""

import sys
import os
import time
import hashlib
import json
import requests
import io
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from PIL import Image
import numpy as np

# Add API to path
sys.path.append('/Users/davidrose/git/floodmap/src/api')

@dataclass
class TestTile:
    """A test tile configuration."""
    name: str
    z: int
    x: int
    y: int
    water_level: float
    location: str  # Human-readable location
    expected_type: str  # "land", "water", "mixed"

@dataclass
class TestResult:
    """Result of a single tile test."""
    tile: TestTile
    success: bool
    generation_time_ms: float
    error_message: Optional[str] = None
    tile_hash: Optional[str] = None
    content_analysis: Optional[Dict] = None

class VisualRegressionTester:
    """Automated visual regression testing for elevation tiles."""
    
    def __init__(self, base_url: str = "http://localhost:8005"):
        self.base_url = base_url
        self.reference_dir = Path("tests/reference_tiles")
        self.reference_dir.mkdir(parents=True, exist_ok=True)
        
        # Test tiles covering various scenarios
        self.test_tiles = [
            # Tampa Bay area - mixed land/water
            TestTile("Tampa Bay", 11, 556, 857, 2.0, "Tampa, FL", "mixed"),
            TestTile("Tampa Coast", 12, 1113, 1715, 1.5, "Tampa Coast, FL", "mixed"),
            
            # NYC area - urban/water
            TestTile("NYC Harbor", 11, 603, 770, 2.0, "New York Harbor", "mixed"),
            TestTile("Manhattan", 12, 1206, 1540, 1.0, "Manhattan, NY", "land"),
            
            # Miami area - coastal
            TestTile("Miami Beach", 11, 559, 895, 1.5, "Miami Beach, FL", "mixed"),
            
            # Inland areas - should be mostly land
            TestTile("Orlando", 10, 279, 428, 2.0, "Orlando, FL", "land"),
            TestTile("Atlanta", 10, 270, 395, 1.5, "Atlanta, GA", "land"),
            
            # Ocean areas - should be mostly water
            TestTile("Atlantic Ocean", 8, 68, 107, 2.0, "Atlantic Ocean", "water"),
            
            # Edge cases
            TestTile("High Water Level", 11, 556, 857, 10.0, "Tampa High Water", "mixed"),
            TestTile("Low Water Level", 11, 556, 857, 0.1, "Tampa Low Water", "mixed"),
        ]
    
    def run_all_tests(self, save_references: bool = False) -> List[TestResult]:
        """Run all visual regression tests."""
        print("🧪 Starting Visual Regression Tests")
        print("=" * 50)
        
        results = []
        
        for tile in self.test_tiles:
            print(f"\n🔍 Testing {tile.name} ({tile.location})")
            print(f"   Tile: {tile.z}/{tile.x}/{tile.y} @ {tile.water_level}m")
            
            result = self._test_single_tile(tile, save_references)
            results.append(result)
            
            if result.success:
                print(f"   ✅ PASS ({result.generation_time_ms:.0f}ms)")
            else:
                print(f"   ❌ FAIL: {result.error_message}")
        
        self._print_summary(results)
        return results
    
    def _test_single_tile(self, tile: TestTile, save_reference: bool) -> TestResult:
        """Test a single tile."""
        start_time = time.time()
        
        try:
            # Request tile from API (using legacy API that has the performance issue)
            url = f"{self.base_url}/api/tiles/elevation/{tile.water_level}/{tile.z}/{tile.x}/{tile.y}.png"
            response = requests.get(url, timeout=30)
            
            if response.status_code != 200:
                return TestResult(
                    tile=tile,
                    success=False,
                    generation_time_ms=0,
                    error_message=f"HTTP {response.status_code}"
                )
            
            generation_time = (time.time() - start_time) * 1000
            tile_data = response.content
            
            # Calculate tile hash for comparison
            tile_hash = hashlib.md5(tile_data).hexdigest()
            
            # Analyze tile content
            content_analysis = self._analyze_tile_content(tile_data)
            
            # Performance check
            if generation_time > 5000:  # 5 seconds
                return TestResult(
                    tile=tile,
                    success=False,
                    generation_time_ms=generation_time,
                    error_message=f"Too slow: {generation_time:.0f}ms",
                    tile_hash=tile_hash,
                    content_analysis=content_analysis
                )
            
            # Content validation
            validation_error = self._validate_tile_content(tile, content_analysis)
            if validation_error:
                return TestResult(
                    tile=tile,
                    success=False,
                    generation_time_ms=generation_time,
                    error_message=validation_error,
                    tile_hash=tile_hash,
                    content_analysis=content_analysis
                )
            
            # Save reference if requested
            if save_reference:
                self._save_reference_tile(tile, tile_data, tile_hash, content_analysis)
            else:
                # Compare with reference
                comparison_error = self._compare_with_reference(tile, tile_hash, content_analysis)
                if comparison_error:
                    return TestResult(
                        tile=tile,
                        success=False,
                        generation_time_ms=generation_time,
                        error_message=comparison_error,
                        tile_hash=tile_hash,
                        content_analysis=content_analysis
                    )
            
            return TestResult(
                tile=tile,
                success=True,
                generation_time_ms=generation_time,
                tile_hash=tile_hash,
                content_analysis=content_analysis
            )
            
        except Exception as e:
            return TestResult(
                tile=tile,
                success=False,
                generation_time_ms=(time.time() - start_time) * 1000,
                error_message=str(e)
            )
    
    def _analyze_tile_content(self, tile_data: bytes) -> Dict:
        """Analyze the content of a tile."""
        try:
            # Load image
            img = Image.open(io.BytesIO(tile_data))
            img_array = np.array(img)
            
            # Basic statistics
            height, width = img_array.shape[:2]
            is_rgba = len(img_array.shape) == 3 and img_array.shape[2] == 4
            
            analysis = {
                "width": width,
                "height": height,
                "is_rgba": is_rgba,
                "total_pixels": width * height
            }
            
            if is_rgba:
                # Analyze transparency
                alpha_channel = img_array[:, :, 3]
                transparent_pixels = (alpha_channel == 0).sum()
                analysis["transparent_pixels"] = int(transparent_pixels)
                analysis["transparency_ratio"] = float(transparent_pixels / (width * height))
                
                # Analyze colors (only non-transparent pixels)
                non_transparent_mask = alpha_channel > 0
                if non_transparent_mask.any():
                    rgb_channels = img_array[:, :, :3]
                    visible_pixels = rgb_channels[non_transparent_mask]
                    
                    analysis["unique_colors"] = len(np.unique(visible_pixels.reshape(-1, 3), axis=0))
                    analysis["has_variation"] = analysis["unique_colors"] > 1
                    
                    # Check for solid colors (problem indicator)
                    if analysis["unique_colors"] == 1:
                        analysis["dominant_color"] = visible_pixels[0].tolist()
                        analysis["is_solid_color"] = True
                    else:
                        analysis["is_solid_color"] = False
                else:
                    analysis["is_fully_transparent"] = True
            
            return analysis
            
        except Exception as e:
            return {"error": str(e)}
    
    def _validate_tile_content(self, tile: TestTile, analysis: Dict) -> Optional[str]:
        """Validate tile content against expectations."""
        if "error" in analysis:
            return f"Content analysis failed: {analysis['error']}"
        
        # Check basic structure
        if analysis.get("width") != 256 or analysis.get("height") != 256:
            return f"Invalid tile size: {analysis.get('width')}x{analysis.get('height')}"
        
        # Check for fully transparent tiles (usually indicates an error)
        if analysis.get("is_fully_transparent"):
            return "Tile is fully transparent"
        
        # Check for solid color tiles (usually indicates coordinate misalignment)
        if analysis.get("is_solid_color") and tile.expected_type != "water":
            color = analysis.get("dominant_color", [])
            # Blue tiles might be valid for water areas
            if not (len(color) == 3 and color[0] < 100 and color[1] < 100 and color[2] > 150):
                return f"Tile is solid color: {color}"
        
        # Check for reasonable color variation
        if analysis.get("unique_colors", 0) < 2 and tile.expected_type == "mixed":
            return "Mixed terrain tile has no color variation"
        
        # Check transparency ratio
        transparency_ratio = analysis.get("transparency_ratio", 0)
        if tile.expected_type == "water" and transparency_ratio < 0.3:
            return f"Water tile has low transparency: {transparency_ratio:.2f}"
        
        return None
    
    def _save_reference_tile(self, tile: TestTile, tile_data: bytes, tile_hash: str, analysis: Dict):
        """Save a reference tile and its metadata."""
        reference_file = self.reference_dir / f"{tile.name.replace(' ', '_')}.png"
        metadata_file = self.reference_dir / f"{tile.name.replace(' ', '_')}.json"
        
        # Save tile image
        with open(reference_file, 'wb') as f:
            f.write(tile_data)
        
        # Save metadata
        metadata = {
            "tile": {
                "name": tile.name,
                "z": tile.z,
                "x": tile.x,
                "y": tile.y,
                "water_level": tile.water_level,
                "location": tile.location,
                "expected_type": tile.expected_type
            },
            "hash": tile_hash,
            "analysis": analysis,
            "created_at": time.time()
        }
        
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
    
    def _compare_with_reference(self, tile: TestTile, tile_hash: str, analysis: Dict) -> Optional[str]:
        """Compare tile with reference."""
        metadata_file = self.reference_dir / f"{tile.name.replace(' ', '_')}.json"
        
        if not metadata_file.exists():
            return "No reference tile found (run with --save-references first)"
        
        try:
            with open(metadata_file, 'r') as f:
                reference_metadata = json.load(f)
            
            # Compare hash (exact match)
            if tile_hash == reference_metadata["hash"]:
                return None  # Perfect match
            
            # Compare analysis (allow minor differences)
            ref_analysis = reference_metadata["analysis"]
            
            # Check critical properties
            if analysis.get("is_solid_color") != ref_analysis.get("is_solid_color"):
                return "Solid color status changed"
            
            if analysis.get("is_fully_transparent") != ref_analysis.get("is_fully_transparent"):
                return "Transparency status changed"
            
            # Allow some variation in color count (compression differences)
            unique_colors_diff = abs(analysis.get("unique_colors", 0) - ref_analysis.get("unique_colors", 0))
            if unique_colors_diff > 50:  # Allow 50 color difference
                return f"Color variation changed significantly: {unique_colors_diff}"
            
            # Check transparency ratio (allow 10% difference)
            transparency_diff = abs(analysis.get("transparency_ratio", 0) - ref_analysis.get("transparency_ratio", 0))
            if transparency_diff > 0.1:
                return f"Transparency ratio changed: {transparency_diff:.3f}"
            
            return None  # Content is similar enough
            
        except Exception as e:
            return f"Reference comparison failed: {e}"
    
    def _print_summary(self, results: List[TestResult]):
        """Print test summary."""
        print("\n" + "=" * 50)
        print("📊 Test Summary")
        
        passed = sum(1 for r in results if r.success)
        failed = len(results) - passed
        
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        
        if failed > 0:
            print("\n🚨 Failed Tests:")
            for result in results:
                if not result.success:
                    print(f"   {result.tile.name}: {result.error_message}")
        
        # Performance summary
        times = [r.generation_time_ms for r in results if r.success]
        if times:
            avg_time = sum(times) / len(times)
            max_time = max(times)
            print(f"\n⏱️  Performance:")
            print(f"   Average: {avg_time:.0f}ms")
            print(f"   Slowest: {max_time:.0f}ms")
            
            if max_time > 3000:
                print(f"   ⚠️  Some tiles are slow (>{3000}ms)")
        
        print("\n" + "=" * 50)


def main():
    """Main test runner."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Visual regression testing for flood map tiles")
    parser.add_argument("--save-references", action="store_true", 
                       help="Save current tiles as reference images")
    parser.add_argument("--base-url", default="http://localhost:8005",
                       help="Base URL for API server")
    
    args = parser.parse_args()
    
    tester = VisualRegressionTester(base_url=args.base_url)
    results = tester.run_all_tests(save_references=args.save_references)
    
    # Exit with error code if any tests failed
    failed_count = sum(1 for r in results if not r.success)
    if failed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()