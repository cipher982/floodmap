#!/usr/bin/env python3
"""
Browser Performance Testing with Playwright
Tests real user interactions: zoom, pan, water level changes
"""

import asyncio
import json
import time
from pathlib import Path
from playwright.async_api import async_playwright
from typing import List, Dict, Any
import statistics

class BrowserPerformanceTest:
    """Real browser performance testing."""
    
    def __init__(self, base_url: str = "http://localhost:5002"):
        self.base_url = base_url
        self.results = []
    
    async def setup_browser(self):
        """Setup browser and page."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=False)  # Visible for debugging
        self.context = await self.browser.new_context()
        
        # Enable performance monitoring
        self.page = await self.context.new_page()
        
        # Monitor network requests
        self.network_requests = []
        self.page.on("request", lambda request: self.network_requests.append({
            "url": request.url,
            "method": request.method,
            "timestamp": time.time()
        }))
        
        self.page.on("response", lambda response: self._on_response(response))
        
        # Monitor console for errors
        self.page.on("console", lambda msg: print(f"Console: {msg.text}"))
        
    def _on_response(self, response):
        """Track response timing."""
        if "/api/v1/tiles/elevation-data/" in response.url:
            # Find matching request
            for req in reversed(self.network_requests):
                if req["url"] == response.url:
                    duration = (time.time() - req["timestamp"]) * 1000
                    self.results.append({
                        "type": "tile_request",
                        "url": response.url,
                        "status": response.status,
                        "duration_ms": duration,
                        "timestamp": time.time()
                    })
                    break
    
    async def test_initial_load(self) -> Dict[str, Any]:
        """Test initial page load performance."""
        print("🌍 Testing initial page load...")
        
        start_time = time.time()
        await self.page.goto(self.base_url)
        
        # Wait for map to be ready (check for canvas or map container)
        try:
            await self.page.wait_for_selector("#map", timeout=10000)
            await self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception as e:
            print(f"Warning: Map load timeout: {e}")
        
        load_time = (time.time() - start_time) * 1000
        
        # Count initial tile requests
        initial_tiles = len([r for r in self.results if r["type"] == "tile_request"])
        
        return {
            "load_time_ms": load_time,
            "initial_tile_count": initial_tiles,
            "success": True
        }
    
    async def test_zoom_performance(self, zoom_levels: List[int] = None) -> Dict[str, Any]:
        """Test zoom performance."""
        if zoom_levels is None:
            zoom_levels = [10, 11, 12, 13, 12, 11, 10]  # Zoom in and out
        
        print(f"🔍 Testing zoom performance: {zoom_levels}")
        
        zoom_results = []
        
        for zoom_level in zoom_levels:
            # Clear previous results
            before_count = len(self.results)
            
            start_time = time.time()
            
            # Execute zoom (this depends on your map implementation)
            # You may need to adjust these selectors based on your actual HTML
            await self.page.evaluate(f"""
                // Prefer map from FloodMapClient if available
                const map = (window.floodMap && window.floodMap.map) || window.map;
                if (map && map.setZoom) {{
                    map.setZoom({zoom_level});
                }}
            """)
            
            # Wait for tiles to load
            await asyncio.sleep(2)  # Give tiles time to load
            
            end_time = time.time()
            
            # Count new tile requests
            new_tiles = len(self.results) - before_count
            duration = (end_time - start_time) * 1000
            
            zoom_results.append({
                "zoom_level": zoom_level,
                "duration_ms": duration,
                "tile_count": new_tiles
            })
        
        return {
            "zoom_operations": zoom_results,
            "avg_zoom_time": statistics.mean([r["duration_ms"] for r in zoom_results]),
            "total_tiles_loaded": sum(r["tile_count"] for r in zoom_results)
        }
    
    async def test_pan_performance(self, pan_count: int = 10) -> Dict[str, Any]:
        """Test panning performance."""
        print(f"👆 Testing pan performance ({pan_count} operations)...")
        
        pan_results = []
        
        for i in range(pan_count):
            before_count = len(self.results)
            start_time = time.time()
            
            # Simulate pan by changing map center
            offset_x = (i % 3 - 1) * 0.01  # Small random movements
            offset_y = (i % 3 - 1) * 0.01
            
            await self.page.evaluate(f"""
                const map = (window.floodMap && window.floodMap.map) || window.map;
                if (map && map.panBy) {{
                    map.panBy([{offset_x * 100}, {offset_y * 100}]);
                }} else if (map && map.setCenter && map.getCenter) {{
                    const center = map.getCenter();
                    map.setCenter([center[0] + {offset_x}, center[1] + {offset_y}]);
                }}
            """)
            
            # Wait for tiles to load
            await asyncio.sleep(1)
            
            end_time = time.time()
            new_tiles = len(self.results) - before_count
            
            pan_results.append({
                "pan_operation": i,
                "duration_ms": (end_time - start_time) * 1000,
                "tile_count": new_tiles
            })
        
        return {
            "pan_operations": pan_results,
            "avg_pan_time": statistics.mean([r["duration_ms"] for r in pan_results]),
            "total_tiles_loaded": sum(r["tile_count"] for r in pan_results)
        }
    
    async def test_water_level_change(self, levels: List[float] = None) -> Dict[str, Any]:
        """Test water level change performance."""
        if levels is None:
            levels = [1.0, 2.0, 3.0, 4.0, 5.0, 2.5]
        
        print(f"🌊 Testing water level changes: {levels}")
        
        level_results = []
        
        for level in levels:
            before_count = len(self.results)
            start_time = time.time()
            
            # Change water level (depends on your UI implementation)
            await self.page.evaluate(f"""
                // Assuming you have a water level slider or input
                const slider = document.querySelector('#water-level-slider') || 
                              document.querySelector('input[type="range"]');
                if (slider) {{
                    slider.value = {level};
                    slider.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
                
                // Or if you have a direct API
                if (window.setWaterLevel) {{
                    window.setWaterLevel({level});
                }}
            """)
            
            # Wait for tiles to reload
            await asyncio.sleep(3)
            
            end_time = time.time()
            new_tiles = len(self.results) - before_count
            
            level_results.append({
                "water_level": level,
                "duration_ms": (end_time - start_time) * 1000,
                "tile_count": new_tiles
            })
        
        return {
            "water_level_changes": level_results,
            "avg_change_time": statistics.mean([r["duration_ms"] for r in level_results]),
            "total_tiles_loaded": sum(r["tile_count"] for r in level_results)
        }
    
    async def test_heavy_interaction(self) -> Dict[str, Any]:
        """Test rapid user interactions."""
        print("⚡ Testing heavy interaction scenario...")
        
        start_time = time.time()
        before_count = len(self.results)
        
        # Rapid zoom and pan sequence
        for i in range(5):
            # Quick zoom
            await self.page.evaluate(f"window.map && window.map.setZoom && window.map.setZoom({11 + i % 2})")
            await asyncio.sleep(0.5)
            
            # Quick pan
            await self.page.evaluate(f"window.map && window.map.panBy && window.map.panBy([{i * 20}, {i * 10}])")
            await asyncio.sleep(0.5)
        
        # Wait for all tiles to settle
        await asyncio.sleep(5)
        
        end_time = time.time()
        total_tiles = len(self.results) - before_count
        
        return {
            "total_duration_ms": (end_time - start_time) * 1000,
            "total_tiles_loaded": total_tiles,
            "avg_tiles_per_second": total_tiles / (end_time - start_time) if end_time > start_time else 0
        }
    
    async def cleanup(self):
        """Cleanup browser resources."""
        await self.browser.close()
        await self.playwright.stop()
    
    async def run_full_test(self) -> Dict[str, Any]:
        """Run comprehensive browser performance test."""
        await self.setup_browser()
        
        try:
            results = {
                "initial_load": await self.test_initial_load(),
                "zoom_performance": await self.test_zoom_performance(),
                "pan_performance": await self.test_pan_performance(),
                "water_level_performance": await self.test_water_level_change(),
                "heavy_interaction": await self.test_heavy_interaction()
            }
            
            # Analyze all tile requests
            tile_requests = [r for r in self.results if r["type"] == "tile_request"]
            if tile_requests:
                durations = [r["duration_ms"] for r in tile_requests]
                results["tile_analysis"] = {
                    "total_requests": len(tile_requests),
                    "avg_duration_ms": statistics.mean(durations),
                    "p95_duration_ms": statistics.quantiles(durations, n=20)[18] if len(durations) > 1 else durations[0],
                    "fastest_ms": min(durations),
                    "slowest_ms": max(durations),
                    "success_rate": len([r for r in tile_requests if r["status"] == 200]) / len(tile_requests)
                }
            
            return results
            
        finally:
            await self.cleanup()

def print_browser_results(results: Dict[str, Any]):
    """Print browser test results."""
    print("\\n" + "=" * 80)
    print("🌐 BROWSER PERFORMANCE RESULTS")
    print("=" * 80)
    
    # Initial load
    if "initial_load" in results:
        load = results["initial_load"]
        print(f"\\n📄 INITIAL LOAD")
        print(f"  Load Time: {load['load_time_ms']:.0f} ms")
        print(f"  Initial Tiles: {load['initial_tile_count']}")
    
    # Tile analysis
    if "tile_analysis" in results:
        tiles = results["tile_analysis"]
        print(f"\\n🏔️ TILE PERFORMANCE")
        print(f"  Total Requests: {tiles['total_requests']}")
        print(f"  Average Duration: {tiles['avg_duration_ms']:.1f} ms")
        print(f"  95th Percentile: {tiles['p95_duration_ms']:.1f} ms")
        print(f"  Fastest: {tiles['fastest_ms']:.1f} ms")
        print(f"  Slowest: {tiles['slowest_ms']:.1f} ms")
        print(f"  Success Rate: {tiles['success_rate']:.1%}")
    
    # Zoom performance
    if "zoom_performance" in results:
        zoom = results["zoom_performance"]
        print(f"\\n🔍 ZOOM PERFORMANCE")
        print(f"  Average Zoom Time: {zoom['avg_zoom_time']:.0f} ms")
        print(f"  Total Tiles Loaded: {zoom['total_tiles_loaded']}")
    
    # Pan performance
    if "pan_performance" in results:
        pan = results["pan_performance"]
        print(f"\\n👆 PAN PERFORMANCE")
        print(f"  Average Pan Time: {pan['avg_pan_time']:.0f} ms")
        print(f"  Total Tiles Loaded: {pan['total_tiles_loaded']}")
    
    # Water level performance
    if "water_level_performance" in results:
        water = results["water_level_performance"]
        print(f"\\n🌊 WATER LEVEL PERFORMANCE")
        print(f"  Average Change Time: {water['avg_change_time']:.0f} ms")
        print(f"  Total Tiles Loaded: {water['total_tiles_loaded']}")
    
    # Heavy interaction
    if "heavy_interaction" in results:
        heavy = results["heavy_interaction"]
        print(f"\\n⚡ HEAVY INTERACTION")
        print(f"  Total Duration: {heavy['total_duration_ms']:.0f} ms")
        print(f"  Tiles per Second: {heavy['avg_tiles_per_second']:.1f}")

async def main():
    """Run browser performance test."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Browser performance test for flood map')
    parser.add_argument('--url', default='http://localhost:5002',
                       help='Base URL for the application')
    parser.add_argument('--output', help='Output results to JSON file')
    
    args = parser.parse_args()
    
    test = BrowserPerformanceTest(args.url)
    results = await test.run_full_test()
    
    print_browser_results(results)
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\\n📄 Results saved to {args.output}")

if __name__ == "__main__":
    asyncio.run(main())
