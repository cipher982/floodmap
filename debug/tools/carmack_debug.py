#!/usr/bin/env python3
"""
Carmack-style debugging: Close the loop between expectation and reality.
"""

import requests
import numpy as np
from PIL import Image
import io
import hashlib
import json
from pathlib import Path

class TileReality:
    """Capture and analyze the actual reality of what tiles are being served."""
    
    def __init__(self):
        self.capture_dir = Path("tile_captures")
        self.capture_dir.mkdir(exist_ok=True)
    
    def capture_browser_tile(self, z, x, y, water_level):
        """Capture the exact tile bytes the browser receives."""
        url = f"http://localhost:8000/api/tiles/elevation/{water_level}/{z}/{x}/{y}.png"
        
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                # Save the exact bytes
                tile_hash = hashlib.md5(response.content).hexdigest()[:8]
                filename = f"browser_{z}_{x}_{y}_{water_level}_{tile_hash}.png"
                filepath = self.capture_dir / filename
                
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                
                # Analyze the pixels
                img = Image.open(io.BytesIO(response.content))
                pixels = np.array(img)
                
                analysis = {
                    'url': url,
                    'status_code': response.status_code,
                    'bytes': len(response.content),
                    'hash': tile_hash,
                    'filepath': str(filepath),
                    'shape': pixels.shape,
                    'unique_colors': len(np.unique(pixels.reshape(-1, pixels.shape[2]), axis=0)),
                    'mean_color': np.mean(pixels, axis=(0,1)).astype(int).tolist(),
                    'is_solid': len(np.unique(pixels.reshape(-1, pixels.shape[2]), axis=0)) == 1,
                    'headers': dict(response.headers)
                }
                
                return analysis
            else:
                return {'error': f'HTTP {response.status_code}', 'url': url}
        except Exception as e:
            return {'error': str(e), 'url': url}
    
    def compare_tiles(self, tile1_analysis, tile2_analysis):
        """Compare two tile analyses to find differences."""
        if tile1_analysis.get('error') or tile2_analysis.get('error'):
            return {'error': 'Cannot compare tiles with errors'}
        
        # Load both images
        img1 = Image.open(tile1_analysis['filepath'])
        img2 = Image.open(tile2_analysis['filepath'])
        
        pixels1 = np.array(img1)
        pixels2 = np.array(img2)
        
        # Calculate differences
        if pixels1.shape == pixels2.shape:
            diff = np.abs(pixels1.astype(float) - pixels2.astype(float))
            max_diff = np.max(diff)
            mean_diff = np.mean(diff)
            identical = np.array_equal(pixels1, pixels2)
        else:
            max_diff = float('inf')
            mean_diff = float('inf')
            identical = False
        
        return {
            'identical': identical,
            'max_pixel_diff': max_diff,
            'mean_pixel_diff': mean_diff,
            'hash1': tile1_analysis['hash'],
            'hash2': tile2_analysis['hash'],
            'same_hash': tile1_analysis['hash'] == tile2_analysis['hash']
        }
    
    def test_water_level_consistency(self, z, x, y, water_levels):
        """Test how a tile changes across different water levels."""
        print(f"🔬 Testing tile {z}/{x}/{y} across water levels: {water_levels}")
        
        results = []
        for wl in water_levels:
            print(f"   Testing water level {wl}m...")
            analysis = self.capture_browser_tile(z, x, y, wl)
            results.append((wl, analysis))
        
        # Analyze the sequence
        print(f"\n📊 Results:")
        for wl, analysis in results:
            if 'error' not in analysis:
                solid_str = "SOLID" if analysis['is_solid'] else "VARIED"
                print(f"   {wl}m: {analysis['unique_colors']} colors, {solid_str}, hash={analysis['hash']}")
            else:
                print(f"   {wl}m: ERROR - {analysis['error']}")
        
        # Check for consistency patterns
        hashes = [r[1].get('hash') for r in results if 'hash' in r[1]]
        unique_hashes = len(set(hashes))
        
        print(f"\n🎯 Analysis:")
        print(f"   Unique tile hashes: {unique_hashes}/{len(results)}")
        
        if unique_hashes == 1:
            print(f"   🚨 PROBLEM: All water levels produce identical tiles!")
        elif unique_hashes == len(results):
            print(f"   ✅ Good: Each water level produces different tiles")
        else:
            print(f"   ⚠️ Mixed: Some water levels produce identical tiles")
        
        return results
    
    def test_coordinate_consistency(self, water_level):
        """Test multiple coordinates at same water level."""
        print(f"🗺️ Testing coordinate consistency at water level {water_level}m")
        
        # Test coordinates around the problem area
        coords = [
            (8, 68, 106),  # Known broken tile
            (8, 68, 105),  # Adjacent tile
            (8, 69, 106),  # Adjacent tile
            (8, 67, 106),  # Adjacent tile
        ]
        
        results = []
        for z, x, y in coords:
            print(f"   Testing {z}/{x}/{y}...")
            analysis = self.capture_browser_tile(z, x, y, water_level)
            results.append(((z, x, y), analysis))
        
        print(f"\n📊 Coordinate Results:")
        for coord, analysis in results:
            if 'error' not in analysis:
                solid_str = "SOLID" if analysis['is_solid'] else "VARIED" 
                print(f"   {coord}: {analysis['unique_colors']} colors, {solid_str}, hash={analysis['hash']}")
            else:
                print(f"   {coord}: ERROR - {analysis['error']}")
        
        return results
    
    def test_cache_behavior(self, z, x, y, water_level, iterations=3):
        """Test if the same request returns consistent results."""
        print(f"🔄 Testing cache consistency for {z}/{x}/{y} at {water_level}m ({iterations} requests)")
        
        results = []
        for i in range(iterations):
            print(f"   Request {i+1}/{iterations}...")
            analysis = self.capture_browser_tile(z, x, y, water_level)
            results.append(analysis)
        
        # Check consistency
        hashes = [r.get('hash') for r in results if 'hash' in r]
        unique_hashes = len(set(hashes))
        
        print(f"\n🎯 Cache Analysis:")
        if unique_hashes == 1:
            print(f"   ✅ Consistent: All requests return identical tiles")
        else:
            print(f"   🚨 INCONSISTENT: {unique_hashes} different tiles from {iterations} requests!")
            for i, h in enumerate(hashes):
                print(f"      Request {i+1}: hash={h}")
        
        return results

def main():
    """Run Carmack-style reality testing."""
    print("🚀 Carmack Debugging: Measuring Reality")
    print("="*60)
    
    reality = TileReality()
    
    # Test 1: Water level consistency on known broken tile
    print("\n" + "="*60)
    print("TEST 1: Water Level Consistency")
    water_levels = [3.4, 3.5, 3.6, 3.7, 3.8]
    wl_results = reality.test_water_level_consistency(8, 68, 106, water_levels)
    
    # Test 2: Cache consistency  
    print("\n" + "="*60)
    print("TEST 2: Cache Consistency")
    cache_results = reality.test_cache_behavior(8, 68, 106, 3.6, 3)
    
    # Test 3: Coordinate consistency
    print("\n" + "="*60)
    print("TEST 3: Coordinate Consistency")
    coord_results = reality.test_coordinate_consistency(3.6)
    
    # Summary
    print("\n" + "="*60)
    print("REALITY CHECK SUMMARY")
    print("="*60)
    
    # Check if we can programmatically reproduce what the browser sees
    print("🔍 Gap Analysis:")
    print("   - All tile bytes captured and hashed")
    print("   - Pixel-level analysis available")
    print("   - Ready for expectation vs reality comparison")
    
    print(f"\n📁 All captured tiles saved in: {reality.capture_dir}")
    print("🔧 Next: Compare these with programmatic generation")

if __name__ == "__main__":
    main()