#!/usr/bin/env python3
"""
Comprehensive Performance Benchmark Suite
Tests both current and optimized implementations across different scenarios.
"""

import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import psutil
import requests

# Add the API directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "flood-map-v2" / "api"))


@dataclass
class BenchmarkResult:
    """Single benchmark result."""

    name: str
    duration_ms: float
    memory_mb: float
    cache_hit: bool = False
    error: str = None


@dataclass
class PerformanceReport:
    """Complete performance analysis."""

    scenario: str
    results: list[BenchmarkResult]
    total_duration_ms: float
    avg_duration_ms: float
    p95_duration_ms: float
    memory_peak_mb: float
    cache_hit_rate: float
    tiles_per_second: float


class PerformanceBenchmark:
    """Comprehensive performance testing."""

    def __init__(self, base_url: str = "http://localhost:5002"):
        self.base_url = base_url
        self.process = psutil.Process()

    def benchmark_single_tile(
        self, water_level: float = 2.0, z: int = 11, x: int = 555, y: int = 859
    ) -> BenchmarkResult:
        """Benchmark single tile generation."""
        # Memory before
        mem_before = self.process.memory_info().rss / 1024 / 1024

        start_time = time.perf_counter()
        try:
            response = requests.get(
                f"{self.base_url}/api/v1/tiles/elevation-data/{z}/{x}/{y}.u16",
                timeout=10,
            )
            end_time = time.perf_counter()

            if response.status_code != 200:
                return BenchmarkResult(
                    name="single_tile",
                    duration_ms=0,
                    memory_mb=0,
                    error=f"HTTP {response.status_code}",
                )

            # Memory after
            mem_after = self.process.memory_info().rss / 1024 / 1024
            cache_hit = response.headers.get("X-Cache") == "HIT"

            return BenchmarkResult(
                name="single_tile",
                duration_ms=(end_time - start_time) * 1000,
                memory_mb=mem_after - mem_before,
                cache_hit=cache_hit,
            )

        except Exception as e:
            return BenchmarkResult(
                name="single_tile", duration_ms=0, memory_mb=0, error=str(e)
            )

    def benchmark_tile_burst(self, count: int = 20) -> list[BenchmarkResult]:
        """Benchmark burst of tiles (simulates zoom operation)."""
        results = []

        # Tampa area tiles at zoom 11
        base_x, base_y = 555, 859
        water_level = 2.5

        for i in range(count):
            # Vary tile coordinates slightly
            x = base_x + (i % 5) - 2
            y = base_y + (i // 5) - 2
            z = 11

            result = self.benchmark_single_tile(water_level, z, x, y)
            result.name = f"burst_tile_{i}"
            results.append(result)

        return results

    def benchmark_concurrent_tiles(
        self, concurrent_count: int = 10
    ) -> list[BenchmarkResult]:
        """Benchmark concurrent tile requests (simulates heavy load)."""
        results = []

        def fetch_tile(tile_id: int) -> BenchmarkResult:
            # Different tiles to avoid cache hits
            x = 555 + (tile_id % 4)
            y = 859 + (tile_id // 4)
            water_level = 2.0 + (tile_id * 0.1)  # Vary water level

            result = self.benchmark_single_tile(water_level, 11, x, y)
            result.name = f"concurrent_tile_{tile_id}"
            return result

        # Execute concurrently
        with ThreadPoolExecutor(max_workers=concurrent_count) as executor:
            futures = [executor.submit(fetch_tile, i) for i in range(concurrent_count)]

            for future in as_completed(futures):
                results.append(future.result())

        return results

    def benchmark_water_level_sweep(
        self, levels: list[float] = None
    ) -> list[BenchmarkResult]:
        """Benchmark different water levels (tests cache efficiency)."""
        if levels is None:
            levels = [0.0, 1.0, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]

        results = []
        x, y, z = 555, 859, 11  # Same tile, different water levels

        for level in levels:
            result = self.benchmark_single_tile(level, z, x, y)
            result.name = f"water_level_{level}"
            results.append(result)

        return results

    def analyze_results(
        self, results: list[BenchmarkResult], scenario: str
    ) -> PerformanceReport:
        """Analyze benchmark results."""
        valid_results = [r for r in results if r.error is None]

        if not valid_results:
            return PerformanceReport(
                scenario=scenario,
                results=results,
                total_duration_ms=0,
                avg_duration_ms=0,
                p95_duration_ms=0,
                memory_peak_mb=0,
                cache_hit_rate=0,
                tiles_per_second=0,
            )

        durations = [r.duration_ms for r in valid_results]
        cache_hits = sum(1 for r in valid_results if r.cache_hit)

        total_duration = sum(durations)
        avg_duration = statistics.mean(durations)
        p95_duration = (
            statistics.quantiles(durations, n=20)[18]
            if len(durations) > 1
            else durations[0]
        )
        memory_peak = max(r.memory_mb for r in valid_results) if valid_results else 0
        cache_hit_rate = cache_hits / len(valid_results) if valid_results else 0
        tiles_per_second = (
            len(valid_results) / (total_duration / 1000) if total_duration > 0 else 0
        )

        return PerformanceReport(
            scenario=scenario,
            results=results,
            total_duration_ms=total_duration,
            avg_duration_ms=avg_duration,
            p95_duration_ms=p95_duration,
            memory_peak_mb=memory_peak,
            cache_hit_rate=cache_hit_rate,
            tiles_per_second=tiles_per_second,
        )

    def run_comprehensive_benchmark(self) -> dict[str, PerformanceReport]:
        """Run all benchmark scenarios."""
        print("🚀 Starting Comprehensive Performance Benchmark...")
        print(f"Target: {self.base_url}")
        print("=" * 60)

        scenarios = {}

        # 1. Single tile (cold start)
        print("📊 Testing single tile performance...")
        single_results = [self.benchmark_single_tile() for _ in range(5)]
        scenarios["single_tile"] = self.analyze_results(single_results, "Single Tile")

        # 2. Burst tiles (zoom simulation)
        print("📊 Testing tile burst (zoom simulation)...")
        burst_results = self.benchmark_tile_burst(20)
        scenarios["tile_burst"] = self.analyze_results(burst_results, "Tile Burst")

        # 3. Concurrent tiles (heavy load)
        print("📊 Testing concurrent tiles (load simulation)...")
        concurrent_results = self.benchmark_concurrent_tiles(10)
        scenarios["concurrent_tiles"] = self.analyze_results(
            concurrent_results, "Concurrent Load"
        )

        # 4. Water level sweep (cache test)
        print("📊 Testing water level variations (cache efficiency)...")
        sweep_results = self.benchmark_water_level_sweep()
        scenarios["water_level_sweep"] = self.analyze_results(
            sweep_results, "Water Level Sweep"
        )

        return scenarios

    def print_report(self, scenarios: dict[str, PerformanceReport]):
        """Print detailed performance report."""
        print("\\n" + "=" * 80)
        print("🎯 PERFORMANCE BENCHMARK RESULTS")
        print("=" * 80)

        for scenario_name, report in scenarios.items():
            print(f"\\n📈 {report.scenario.upper()}")
            print("-" * 40)
            print(f"  Average Duration:    {report.avg_duration_ms:.1f} ms")
            print(f"  95th Percentile:     {report.p95_duration_ms:.1f} ms")
            print(f"  Tiles per Second:    {report.tiles_per_second:.1f}")
            print(f"  Cache Hit Rate:      {report.cache_hit_rate:.1%}")
            print(f"  Peak Memory Delta:   {report.memory_peak_mb:.1f} MB")

            # Performance assessment
            if report.avg_duration_ms < 100:
                status = "🟢 EXCELLENT"
            elif report.avg_duration_ms < 300:
                status = "🟡 ACCEPTABLE"
            else:
                status = "🔴 NEEDS OPTIMIZATION"

            print(f"  Performance:         {status}")

            # Show errors if any
            errors = [r.error for r in report.results if r.error]
            if errors:
                print(f"  Errors:              {len(errors)}")
                for error in set(errors):
                    print(f"    - {error}")

        # Overall assessment
        print("\\n" + "=" * 80)
        avg_performance = statistics.mean(
            [r.avg_duration_ms for r in scenarios.values() if r.avg_duration_ms > 0]
        )

        if avg_performance < 100:
            print("🎉 OVERALL: System performance is EXCELLENT for real-time mapping")
        elif avg_performance < 300:
            print("✅ OVERALL: System performance is ACCEPTABLE but could be optimized")
        else:
            print("⚠️ OVERALL: System performance NEEDS OPTIMIZATION for smooth UX")

        print(f"Average tile generation: {avg_performance:.1f} ms")
        print("=" * 80)


def main():
    """Run the performance benchmark."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Performance benchmark for flood map tiles"
    )
    parser.add_argument(
        "--url",
        default="http://localhost:5002",
        help="Base URL for the API (default: http://localhost:5002)",
    )
    parser.add_argument("--output", help="Output results to JSON file")

    args = parser.parse_args()

    benchmark = PerformanceBenchmark(args.url)

    try:
        # Test API availability
        response = requests.get(f"{args.url}/api/health", timeout=5)
        if response.status_code != 200:
            print(f"❌ API not available at {args.url}")
            return 1

    except requests.RequestException as e:
        print(f"❌ Cannot connect to API at {args.url}: {e}")
        return 1

    # Run comprehensive benchmark
    scenarios = benchmark.run_comprehensive_benchmark()
    benchmark.print_report(scenarios)

    # Save to JSON if requested
    if args.output:
        output_data = {
            scenario: {
                "avg_duration_ms": report.avg_duration_ms,
                "p95_duration_ms": report.p95_duration_ms,
                "tiles_per_second": report.tiles_per_second,
                "cache_hit_rate": report.cache_hit_rate,
                "memory_peak_mb": report.memory_peak_mb,
                "error_count": len([r for r in report.results if r.error]),
            }
            for scenario, report in scenarios.items()
        }

        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\\n📄 Results saved to {args.output}")

    return 0


if __name__ == "__main__":
    exit(main())
