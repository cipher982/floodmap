#!/usr/bin/env python3
"""
Automated tile validation - test both vector and elevation tiles objectively
"""

import json
import time

import requests


def test_vector_tiles() -> dict:
    """Test vector tiles (bottom layer) at various zoom levels"""
    base_url = "http://localhost:8080"

    # Test coordinates covering different areas
    test_tiles = [
        # Tampa area
        (9, 143, 193),  # Zoom 9
        (10, 286, 387),  # Zoom 10
        (11, 572, 774),  # Zoom 11
        # NYC area
        (9, 150, 190),
        (10, 301, 380),
        # California
        (9, 89, 195),
        (10, 178, 390),
        # Test edge cases
        (8, 68, 107),  # Lower zoom
        (12, 1144, 1548),  # Higher zoom
    ]

    results = {
        "total_tested": len(test_tiles),
        "successful": 0,
        "failed": 0,
        "details": [],
    }

    print("🔍 Testing vector tiles (bottom layer maps)...")

    for z, x, y in test_tiles:
        try:
            # Test direct tileserver access
            direct_url = f"{base_url}/data/usa-complete/{z}/{x}/{y}.pbf"
            direct_response = requests.get(direct_url, timeout=5)

            # Test legacy API proxy
            legacy_api_url = (
                f"http://localhost:8000/api/v1/tiles/vector/usa/{z}/{x}/{y}.pbf"
            )
            legacy_response = requests.get(legacy_api_url, timeout=5)

            # Test new v1 API
            v1_api_url = (
                f"http://localhost:8000/api/v1/tiles/vector/usa/{z}/{x}/{y}.pbf"
            )
            v1_response = requests.get(v1_api_url, timeout=5)

            direct_size = len(direct_response.content)
            legacy_size = len(legacy_response.content)
            v1_size = len(v1_response.content)

            success = (
                direct_response.status_code == 200
                and legacy_response.status_code == 200
                and v1_response.status_code == 200
                and direct_size > 100  # Valid tile data
                and legacy_size > 100
                and v1_size > 100
            )

            if success:
                results["successful"] += 1
                status = "✅ PASS"
            else:
                results["failed"] += 1
                status = "❌ FAIL"

            results["details"].append(
                {
                    "tile": f"{z}/{x}/{y}",
                    "direct_status": direct_response.status_code,
                    "legacy_api_status": legacy_response.status_code,
                    "v1_api_status": v1_response.status_code,
                    "direct_size": direct_size,
                    "legacy_size": legacy_size,
                    "v1_size": v1_size,
                    "success": success,
                }
            )

            print(
                f"  {status} Vector tile {z}/{x}/{y}: Direct={direct_response.status_code}({direct_size}b), Legacy={legacy_response.status_code}({legacy_size}b), V1={v1_response.status_code}({v1_size}b)"
            )

        except Exception as e:
            results["failed"] += 1
            results["details"].append(
                {"tile": f"{z}/{x}/{y}", "error": str(e), "success": False}
            )
            print(f"  ❌ FAIL Vector tile {z}/{x}/{y}: {e}")

    return results


def test_elevation_tiles() -> dict:
    """Test elevation tiles (top layer flood overlay) at various parameters"""
    base_url = "http://localhost:8000/api"

    # Test coordinates and water levels
    test_tiles = [
        # Tampa area - should have elevation data
        (1.0, 10, 286, 387),
        (2.0, 10, 286, 387),
        (0.5, 11, 572, 774),
        # Different water levels
        (3.0, 10, 286, 387),
        (5.0, 10, 286, 387),
        # Different zoom levels
        (1.0, 9, 143, 193),
        (1.0, 11, 572, 774),
        (1.0, 12, 1144, 1548),
        # Edge cases
        (0.1, 10, 286, 387),  # Low water level
        (10.0, 10, 286, 387),  # High water level
    ]

    results = {
        "total_tested": len(test_tiles),
        "successful": 0,
        "failed": 0,
        "details": [],
        "performance": [],
    }

    print("🔍 Testing elevation tiles (top layer flood overlay)...")

    for water_level, z, x, y in test_tiles:
        try:
            start_time = time.time()

            # Test legacy flood tiles
            legacy_url = f"{base_url}/tiles/elevation/{water_level}/{z}/{x}/{y}.png"
            legacy_response = requests.get(legacy_url, timeout=15)

            # Test v1 flood tiles
            v1_flood_url = f"http://localhost:8000/api/v1/tiles/flood/{water_level}/{z}/{x}/{y}.png"
            v1_flood_response = requests.get(v1_flood_url, timeout=15)

            # Test v1 raw elevation tiles (no water level)
            v1_elevation_url = (
                f"http://localhost:8000/api/v1/tiles/elevation/{z}/{x}/{y}.png"
            )
            v1_elevation_response = requests.get(v1_elevation_url, timeout=15)

            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000

            legacy_size = len(legacy_response.content)
            v1_flood_size = len(v1_flood_response.content)
            v1_elevation_size = len(v1_elevation_response.content)

            # Check if responses are valid PNGs
            legacy_is_png = legacy_response.content.startswith(b"\x89PNG")
            v1_flood_is_png = v1_flood_response.content.startswith(b"\x89PNG")
            v1_elevation_is_png = v1_elevation_response.content.startswith(b"\x89PNG")

            success = (
                legacy_response.status_code in [200, 204]
                and v1_flood_response.status_code in [200, 204]
                and v1_elevation_response.status_code in [200, 204]
                and (legacy_size > 100 or legacy_response.status_code == 204)
                and (v1_flood_size > 100 or v1_flood_response.status_code == 204)
                and (
                    v1_elevation_size > 100 or v1_elevation_response.status_code == 204
                )
            )

            if success:
                results["successful"] += 1
                status = "✅ PASS"
            else:
                results["failed"] += 1
                status = "❌ FAIL"

            # Track performance
            results["performance"].append(duration_ms)

            legacy_cache = legacy_response.headers.get("X-Cache", "UNKNOWN")
            v1_flood_cache = v1_flood_response.headers.get("X-Cache", "UNKNOWN")
            v1_elevation_cache = v1_elevation_response.headers.get("X-Cache", "UNKNOWN")

            results["details"].append(
                {
                    "tile": f"{water_level}m/{z}/{x}/{y}",
                    "legacy_status": legacy_response.status_code,
                    "v1_flood_status": v1_flood_response.status_code,
                    "v1_elevation_status": v1_elevation_response.status_code,
                    "legacy_size": legacy_size,
                    "v1_flood_size": v1_flood_size,
                    "v1_elevation_size": v1_elevation_size,
                    "duration_ms": duration_ms,
                    "success": success,
                }
            )

            print(
                f"  {status} Elevation {water_level}m/{z}/{x}/{y}: Legacy={legacy_response.status_code}({legacy_size}b), V1Flood={v1_flood_response.status_code}({v1_flood_size}b), V1Elev={v1_elevation_response.status_code}({v1_elevation_size}b) {duration_ms:.0f}ms"
            )

        except Exception as e:
            results["failed"] += 1
            results["details"].append(
                {
                    "tile": f"{water_level}m/{z}/{x}/{y}",
                    "error": str(e),
                    "success": False,
                }
            )
            print(f"  ❌ FAIL Elevation tile {water_level}m/{z}/{x}/{y}: {e}")

    return results


def test_concurrent_performance() -> dict:
    """Test concurrent tile generation performance"""
    import concurrent.futures

    print("🔍 Testing concurrent performance...")

    # Simulate map dragging - request multiple tiles at once
    concurrent_requests = [
        ("http://localhost:8000/api/v1/tiles/elevation/10/286/387.png", "elevation"),
        ("http://localhost:8000/api/v1/tiles/elevation/10/287/387.png", "elevation"),
        ("http://localhost:8000/api/v1/tiles/elevation/10/286/388.png", "elevation"),
        ("http://localhost:8000/api/v1/tiles/elevation/10/287/388.png", "elevation"),
        ("http://localhost:8000/api/v1/tiles/vector/usa/10/286/387.pbf", "vector"),
        ("http://localhost:8000/api/v1/tiles/vector/usa/10/287/387.pbf", "vector"),
        ("http://localhost:8000/api/v1/tiles/vector/usa/10/286/388.pbf", "vector"),
        ("http://localhost:8000/api/v1/tiles/vector/usa/10/287/388.pbf", "vector"),
    ]

    def fetch_tile(url_and_type):
        url, tile_type = url_and_type
        start_time = time.time()
        try:
            response = requests.get(url, timeout=15)
            end_time = time.time()
            return {
                "url": url,
                "type": tile_type,
                "status": response.status_code,
                "size": len(response.content),
                "duration_ms": (end_time - start_time) * 1000,
                "success": response.status_code == 200,
            }
        except Exception as e:
            return {"url": url, "type": tile_type, "error": str(e), "success": False}

    # Execute concurrent requests
    start_time = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fetch_tile, req) for req in concurrent_requests]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    end_time = time.time()

    total_time = (end_time - start_time) * 1000
    successful = [r for r in results if r.get("success")]

    performance_data = {
        "total_requests": len(concurrent_requests),
        "successful": len(successful),
        "failed": len(results) - len(successful),
        "total_time_ms": total_time,
        "avg_time_per_tile_ms": total_time / len(concurrent_requests),
        "results": results,
    }

    print(
        f"  Concurrent test: {len(successful)}/{len(concurrent_requests)} successful in {total_time:.0f}ms"
    )

    return performance_data


def main():
    print("🚀 Starting comprehensive tile validation...")
    print("=" * 60)

    # Test vector tiles
    vector_results = test_vector_tiles()
    print(
        f"\n📊 Vector tiles: {vector_results['successful']}/{vector_results['total_tested']} successful"
    )

    # Test elevation tiles
    elevation_results = test_elevation_tiles()
    avg_perf = sum(elevation_results["performance"]) / max(
        len(elevation_results["performance"]), 1
    )
    print(
        f"\n📊 Elevation tiles: {elevation_results['successful']}/{elevation_results['total_tested']} successful, avg {avg_perf:.0f}ms"
    )

    # Test concurrent performance
    concurrent_results = test_concurrent_performance()
    print(
        f"\n📊 Concurrent test: {concurrent_results['successful']}/{concurrent_results['total_requests']} successful in {concurrent_results['total_time_ms']:.0f}ms"
    )

    # Summary
    print("\n" + "=" * 60)
    print("📋 SUMMARY:")
    print(
        f"Vector tiles: {vector_results['successful']}/{vector_results['total_tested']} working"
    )
    print(
        f"Elevation tiles: {elevation_results['successful']}/{elevation_results['total_tested']} working"
    )
    print(
        f"Concurrent performance: {concurrent_results['successful']}/{concurrent_results['total_requests']} working"
    )

    # Identify issues
    issues = []
    if vector_results["failed"] > 0:
        issues.append(f"Vector tiles failing: {vector_results['failed']} failures")
    if elevation_results["failed"] > 0:
        issues.append(
            f"Elevation tiles failing: {elevation_results['failed']} failures"
        )
    if avg_perf > 2000:  # > 2 seconds
        issues.append(f"Elevation tiles slow: {avg_perf:.0f}ms average")
    if concurrent_results["failed"] > 0:
        issues.append(
            f"Concurrent requests failing: {concurrent_results['failed']} failures"
        )

    if issues:
        print("\n🚨 ISSUES FOUND:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\n✅ All tests passed!")

    # Save detailed results
    with open("/tmp/tile_validation_results.json", "w") as f:
        json.dump(
            {
                "vector_tiles": vector_results,
                "elevation_tiles": elevation_results,
                "concurrent_performance": concurrent_results,
                "timestamp": time.time(),
            },
            f,
            indent=2,
        )

    print("\n📁 Detailed results saved to /tmp/tile_validation_results.json")


if __name__ == "__main__":
    main()
