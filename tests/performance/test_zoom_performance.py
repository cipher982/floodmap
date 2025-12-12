#!/usr/bin/env python3
"""
Test zoom-out performance to catch the critical issue where
lower zoom levels (zooming out) become extremely slow.
"""

import time
from dataclasses import dataclass

import pytest
import requests


@dataclass
class ZoomTestResult:
    """Result from testing a single zoom level."""

    zoom: int
    x: int
    y: int
    description: str
    duration_ms: float
    status_code: int
    content_length: int
    cache_hit: bool
    error: str = None


class TestZoomPerformance:
    """Test suite for zoom-level performance issues."""

    @pytest.fixture
    def zoom_test_cases(self) -> list[tuple[int, int, int, str]]:
        """Test cases for different zoom levels."""
        return [
            (12, 1110, 1716, "Very close - Street level"),
            (11, 555, 858, "Close - Neighborhood level"),
            (10, 277, 429, "Medium - City level"),
            (9, 138, 214, "Far - County level"),
            (8, 69, 107, "Very far - Regional level"),
            (7, 34, 53, "Continental - State level"),
            (6, 17, 26, "Multi-state level"),
            (5, 8, 13, "Regional - Multi-state"),
            (4, 4, 6, "Country-wide level"),
        ]

    @pytest.fixture
    def performance_thresholds(self) -> dict[str, float]:
        """Performance thresholds for different use cases."""
        return {
            "excellent": 100,  # < 100ms - Excellent UX
            "good": 500,  # < 500ms - Good UX
            "acceptable": 1000,  # < 1s - Acceptable UX
            "poor": 5000,  # < 5s - Poor UX
            "unacceptable": 10000,  # > 10s - Unacceptable
        }

    def _make_tile_request(
        self, base_url: str, zoom: int, x: int, y: int
    ) -> ZoomTestResult:
        """Make a single tile request with timing."""
        # Add cache buster to ensure we test actual generation time
        cache_buster = int(time.time() * 1000)
        url = f"{base_url}/api/tiles/topographical/{zoom}/{x}/{y}.png?v={cache_buster}"

        start_time = time.perf_counter()
        try:
            response = requests.get(url, timeout=30)
            end_time = time.perf_counter()

            duration_ms = (end_time - start_time) * 1000

            return ZoomTestResult(
                zoom=zoom,
                x=x,
                y=y,
                description=f"Zoom {zoom}",
                duration_ms=duration_ms,
                status_code=response.status_code,
                content_length=len(response.content) if response.content else 0,
                cache_hit=response.headers.get("X-Cache") == "HIT",
                error=None,
            )

        except Exception as e:
            end_time = time.perf_counter()
            duration_ms = (end_time - start_time) * 1000

            return ZoomTestResult(
                zoom=zoom,
                x=x,
                y=y,
                description=f"Zoom {zoom}",
                duration_ms=duration_ms,
                status_code=0,
                content_length=0,
                cache_hit=False,
                error=str(e),
            )

    @pytest.mark.performance
    def test_zoom_levels_performance(
        self, base_url, zoom_test_cases, performance_thresholds
    ):
        """Test that all zoom levels perform within acceptable limits."""
        results = []

        for zoom, x, y, description in zoom_test_cases:
            result = self._make_tile_request(base_url, zoom, x, y)
            result.description = description
            results.append(result)

            # Individual assertions for each zoom level
            assert result.error is None, f"Zoom {zoom} failed: {result.error}"
            assert result.status_code == 200, (
                f"Zoom {zoom} returned {result.status_code}"
            )

            # Performance assertion - fail if > 5 seconds (unacceptable)
            assert result.duration_ms < performance_thresholds["unacceptable"], (
                f"Zoom {zoom} took {result.duration_ms:.0f}ms (> {performance_thresholds['unacceptable']}ms threshold)"
            )

        # Analyze overall performance characteristics
        successful_results = [r for r in results if r.error is None]

        # Check for performance degradation patterns
        slow_zooms = [
            r
            for r in successful_results
            if r.duration_ms > performance_thresholds["poor"]
        ]
        if slow_zooms:
            slow_zoom_info = ", ".join(
                [f"Zoom {r.zoom}: {r.duration_ms:.0f}ms" for r in slow_zooms]
            )
            pytest.fail(
                f"Performance degradation detected at zoom levels: {slow_zoom_info}"
            )

    @pytest.mark.performance
    def test_zoom_performance_consistency(
        self, base_url, zoom_test_cases, performance_thresholds
    ):
        """Test that similar zoom levels have consistent performance."""
        results = []

        # Test a subset of zoom levels multiple times
        test_zooms = [(10, 277, 429), (8, 69, 107), (6, 17, 26)]

        for zoom, x, y in test_zooms:
            zoom_results = []
            for _ in range(3):  # Test 3 times
                result = self._make_tile_request(base_url, zoom, x, y)
                if result.error is None:
                    zoom_results.append(result.duration_ms)

            if zoom_results:
                avg_duration = sum(zoom_results) / len(zoom_results)
                max_duration = max(zoom_results)
                min_duration = min(zoom_results)

                # Check consistency - max shouldn't be more than 3x min
                consistency_ratio = (
                    max_duration / min_duration if min_duration > 0 else float("inf")
                )
                assert consistency_ratio < 3.0, (
                    f"Zoom {zoom} performance inconsistent: {min_duration:.0f}ms to {max_duration:.0f}ms (ratio: {consistency_ratio:.1f})"
                )

    @pytest.mark.slow
    def test_zoom_out_sequence_performance(self, base_url):
        """Test zooming out sequence (simulating user behavior)."""
        # Simulate user zooming out from street level to country level
        zoom_sequence = [12, 11, 10, 9, 8, 7, 6, 5, 4]
        x, y = 1110, 1716  # Start coordinates

        results = []
        for zoom in zoom_sequence:
            # Adjust x,y for zoom level (approximate)
            adjusted_x = x // (2 ** (12 - zoom))
            adjusted_y = y // (2 ** (12 - zoom))

            result = self._make_tile_request(base_url, zoom, adjusted_x, adjusted_y)
            results.append(result)

            # Each zoom level should be usable
            assert result.error is None, f"Zoom {zoom} failed during zoom-out sequence"
            assert result.status_code == 200, (
                f"Zoom {zoom} returned {result.status_code}"
            )

        # Check that performance doesn't degrade exponentially
        durations = [r.duration_ms for r in results if r.error is None]
        if len(durations) >= 2:
            max_duration = max(durations)
            min_duration = min(durations)

            # Performance shouldn't degrade more than 100x
            degradation_ratio = max_duration / min_duration
            assert degradation_ratio < 100, (
                f"Zoom-out performance degrades too much: {degradation_ratio:.1f}x slower"
            )

    @pytest.mark.performance
    def test_critical_zoom_levels_fast(self, base_url, performance_thresholds):
        """Test that critical zoom levels (commonly used) are fast."""
        # These are the most commonly used zoom levels
        critical_zooms = [
            (10, 277, 429),  # City level
            (8, 69, 107),  # Regional level
            (6, 17, 26),  # Multi-state level
        ]

        for zoom, x, y in critical_zooms:
            result = self._make_tile_request(base_url, zoom, x, y)

            assert result.error is None, f"Critical zoom {zoom} failed: {result.error}"
            assert result.status_code == 200, (
                f"Critical zoom {zoom} returned {result.status_code}"
            )

            # Critical zoom levels should be fast (< 1 second)
            assert result.duration_ms < performance_thresholds["acceptable"], (
                f"Critical zoom {zoom} too slow: {result.duration_ms:.0f}ms (should be < {performance_thresholds['acceptable']}ms)"
            )


if __name__ == "__main__":
    # Can be run directly for debugging
    pytest.main([__file__, "-v", "-m", "performance"])
