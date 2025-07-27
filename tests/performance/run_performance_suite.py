#!/usr/bin/env python3
"""
Complete Performance Testing Suite
Runs both synthetic benchmarks and browser tests, compares results.
"""

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any
import requests

class PerformanceTestSuite:
    """Orchestrates complete performance testing."""
    
    def __init__(self, base_url: str = "http://localhost:5002"):
        self.base_url = base_url
        self.results = {}
    
    def check_service_availability(self) -> bool:
        """Check if the service is running."""
        try:
            response = requests.get(f"{self.base_url}/api/health", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def run_synthetic_benchmarks(self) -> Dict[str, Any]:
        """Run synthetic performance benchmarks."""
        print("🔬 Running Synthetic Benchmarks...")
        
        try:
            # Run the benchmark script
            result = subprocess.run([
                sys.executable, 
                str(Path(__file__).parent / "performance_benchmark.py"),
                "--url", self.base_url,
                "--output", "/tmp/synthetic_results.json"
            ], capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                with open("/tmp/synthetic_results.json", 'r') as f:
                    return json.load(f)
            else:
                print(f"Synthetic benchmark failed: {result.stderr}")
                return {"error": result.stderr}
                
        except Exception as e:
            print(f"Error running synthetic benchmarks: {e}")
            return {"error": str(e)}
    
    async def run_browser_tests(self) -> Dict[str, Any]:
        """Run browser performance tests."""
        print("🌐 Running Browser Performance Tests...")
        
        try:
            # Import here to avoid dependency issues
            from browser_performance_test import BrowserPerformanceTest
            
            test = BrowserPerformanceTest(self.base_url)
            return await test.run_full_test()
            
        except ImportError as e:
            print(f"Playwright not available: {e}")
            print("Install with: pip install playwright && playwright install")
            return {"error": "Playwright not installed"}
        except Exception as e:
            print(f"Browser test failed: {e}")
            return {"error": str(e)}
    
    def analyze_combined_results(self, synthetic: Dict[str, Any], browser: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze and compare synthetic vs browser results."""
        analysis = {
            "synthetic_available": "error" not in synthetic,
            "browser_available": "error" not in browser,
            "comparison": {}
        }
        
        if analysis["synthetic_available"] and analysis["browser_available"]:
            # Compare tile performance
            if "single_tile" in synthetic and "tile_analysis" in browser:
                synth_avg = synthetic["single_tile"]["avg_duration_ms"]
                browser_avg = browser["tile_analysis"]["avg_duration_ms"]
                
                analysis["comparison"]["tile_performance"] = {
                    "synthetic_avg_ms": synth_avg,
                    "browser_avg_ms": browser_avg,
                    "browser_overhead_ms": browser_avg - synth_avg,
                    "overhead_percentage": ((browser_avg - synth_avg) / synth_avg * 100) if synth_avg > 0 else 0
                }
            
            # Performance recommendations
            recommendations = []
            
            if analysis["synthetic_available"]:
                if "single_tile" in synthetic:
                    avg_tile_time = synthetic["single_tile"]["avg_duration_ms"]
                    if avg_tile_time > 500:
                        recommendations.append("🔴 CRITICAL: Tile generation >500ms - optimize elevation loading")
                    elif avg_tile_time > 200:
                        recommendations.append("🟡 WARNING: Tile generation >200ms - consider caching improvements")
                    else:
                        recommendations.append("🟢 GOOD: Tile generation under 200ms")
                
                if "concurrent_tiles" in synthetic:
                    concurrent_perf = synthetic["concurrent_tiles"]["avg_duration_ms"]
                    if concurrent_perf > avg_tile_time * 2:
                        recommendations.append("🔴 CRITICAL: Poor concurrent performance - threading issues")
            
            if analysis["browser_available"]:
                if "tile_analysis" in browser:
                    success_rate = browser["tile_analysis"]["success_rate"]
                    if success_rate < 0.95:
                        recommendations.append(f"🔴 CRITICAL: {success_rate:.1%} tile success rate - network/server issues")
                    elif success_rate < 0.99:
                        recommendations.append(f"🟡 WARNING: {success_rate:.1%} tile success rate")
            
            analysis["recommendations"] = recommendations
        
        return analysis
    
    def print_comprehensive_report(self, synthetic: Dict[str, Any], browser: Dict[str, Any], analysis: Dict[str, Any]):
        """Print comprehensive performance report."""
        print("\\n" + "=" * 100)
        print("🎯 COMPREHENSIVE PERFORMANCE REPORT")
        print("=" * 100)
        
        # System info
        print(f"\\n🖥️ SYSTEM INFO")
        print(f"  Target URL: {self.base_url}")
        print(f"  Test Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Synthetic results summary
        if analysis["synthetic_available"]:
            print(f"\\n🔬 SYNTHETIC BENCHMARK SUMMARY")
            if "single_tile" in synthetic:
                st = synthetic["single_tile"]
                print(f"  Single Tile Avg: {st['avg_duration_ms']:.1f} ms")
                print(f"  Cache Hit Rate: {st['cache_hit_rate']:.1%}")
            
            if "concurrent_tiles" in synthetic:
                ct = synthetic["concurrent_tiles"]
                print(f"  Concurrent Avg: {ct['avg_duration_ms']:.1f} ms")
                print(f"  Throughput: {ct['tiles_per_second']:.1f} tiles/sec")
        
        # Browser results summary
        if analysis["browser_available"]:
            print(f"\\n🌐 BROWSER TEST SUMMARY")
            if "tile_analysis" in browser:
                ta = browser["tile_analysis"]
                print(f"  Browser Tile Avg: {ta['avg_duration_ms']:.1f} ms")
                print(f"  Success Rate: {ta['success_rate']:.1%}")
                print(f"  Total Requests: {ta['total_requests']}")
        
        # Comparison
        if "tile_performance" in analysis["comparison"]:
            comp = analysis["comparison"]["tile_performance"]
            print(f"\\n⚖️ SYNTHETIC VS BROWSER COMPARISON")
            print(f"  Synthetic: {comp['synthetic_avg_ms']:.1f} ms")
            print(f"  Browser: {comp['browser_avg_ms']:.1f} ms")
            print(f"  Browser Overhead: +{comp['browser_overhead_ms']:.1f} ms ({comp['overhead_percentage']:.1f}%)")
        
        # Recommendations
        if "recommendations" in analysis:
            print(f"\\n💡 PERFORMANCE RECOMMENDATIONS")
            for rec in analysis["recommendations"]:
                print(f"  {rec}")
        
        # Environment-specific advice
        print(f"\\n🌍 DEPLOYMENT CONSIDERATIONS")
        print(f"  • Local (M3 Max): Optimize for CPU/memory efficiency")
        print(f"  • VPS Deployment: Focus on I/O optimization and caching")
        print(f"  • Network: Add CDN for static tiles, consider HTTP/2")
        print(f"  • Scaling: Implement Redis cache, horizontal scaling")
        
        print("=" * 100)
    
    async def run_complete_suite(self) -> Dict[str, Any]:
        """Run the complete performance test suite."""
        print("🚀 Starting Complete Performance Test Suite")
        print(f"Target: {self.base_url}")
        
        # Check service
        if not self.check_service_availability():
            print(f"❌ Service not available at {self.base_url}")
            return {"error": "Service unavailable"}
        
        print("✅ Service is available")
        
        # Run tests
        synthetic_results = self.run_synthetic_benchmarks()
        browser_results = await self.run_browser_tests()
        
        # Analyze
        analysis = self.analyze_combined_results(synthetic_results, browser_results)
        
        # Report  
        self.print_comprehensive_report(synthetic_results, browser_results, analysis)
        
        return {
            "synthetic": synthetic_results,
            "browser": browser_results,
            "analysis": analysis,
            "timestamp": time.time(),
            "target_url": self.base_url
        }

async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Complete performance test suite')
    parser.add_argument('--url', default='http://localhost:5002',
                       help='Base URL for testing')
    parser.add_argument('--output', help='Save complete results to JSON file')
    parser.add_argument('--synthetic-only', action='store_true',
                       help='Run only synthetic benchmarks (skip browser tests)')
    
    args = parser.parse_args()
    
    suite = PerformanceTestSuite(args.url)
    
    if args.synthetic_only:
        print("🔬 Running synthetic benchmarks only...")
        results = suite.run_synthetic_benchmarks()
        print("Results:", json.dumps(results, indent=2))
    else:
        results = await suite.run_complete_suite()
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\\n📄 Complete results saved to {args.output}")

if __name__ == "__main__":
    asyncio.run(main())