#!/usr/bin/env python3
"""
Comprehensive test runner for floodmap test suite.
Provides different test modes and reporting options.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class TestRunner:
    """Comprehensive test runner with multiple modes."""

    def __init__(self, project_root: Path = None):
        self.project_root = project_root or Path(__file__).parent.parent
        self.test_dir = self.project_root / "tests"

    def run_unit_tests(self, verbose: bool = False) -> int:
        """Run fast unit tests."""
        cmd = ["uv", "run", "pytest", "-m", "unit", "--tb=short"]
        if verbose:
            cmd.append("-v")

        print("🧪 Running unit tests...")
        return subprocess.run(cmd, cwd=self.project_root).returncode

    def run_integration_tests(self, verbose: bool = False) -> int:
        """Run integration tests (requires running services)."""
        cmd = ["uv", "run", "pytest", "-m", "integration", "--tb=short"]
        if verbose:
            cmd.append("-v")

        print("🔗 Running integration tests...")
        return subprocess.run(cmd, cwd=self.project_root).returncode

    def run_performance_tests(self, verbose: bool = False) -> int:
        """Run performance tests."""
        cmd = ["uv", "run", "pytest", "-m", "performance", "--tb=short"]
        if verbose:
            cmd.append("-v")

        print("🚀 Running performance tests...")
        return subprocess.run(cmd, cwd=self.project_root).returncode

    def run_security_tests(self, verbose: bool = False) -> int:
        """Run security tests."""
        cmd = ["uv", "run", "pytest", "-m", "security", "--tb=short"]
        if verbose:
            cmd.append("-v")

        print("🔒 Running security tests...")
        return subprocess.run(cmd, cwd=self.project_root).returncode

    def run_e2e_tests(self, verbose: bool = False) -> int:
        """Run end-to-end tests."""
        cmd = ["uv", "run", "pytest", "-m", "e2e", "--tb=short"]
        if verbose:
            cmd.append("-v")

        print("🌐 Running end-to-end tests...")
        return subprocess.run(cmd, cwd=self.project_root).returncode

    def run_visual_tests(self, verbose: bool = False) -> int:
        """Run visual regression tests."""
        cmd = ["uv", "run", "pytest", "-m", "visual", "--tb=short"]
        if verbose:
            cmd.append("-v")

        print("👁️ Running visual regression tests...")
        return subprocess.run(cmd, cwd=self.project_root).returncode

    def run_slow_tests(self, verbose: bool = False) -> int:
        """Run slow tests."""
        cmd = ["uv", "run", "pytest", "-m", "slow", "--runslow", "--tb=short"]
        if verbose:
            cmd.append("-v")

        print("🐌 Running slow tests...")
        return subprocess.run(cmd, cwd=self.project_root).returncode

    def run_all_tests(self, verbose: bool = False, include_slow: bool = False) -> int:
        """Run all tests."""
        cmd = ["uv", "run", "pytest", "--tb=short"]
        if verbose:
            cmd.append("-v")
        if include_slow:
            cmd.append("--runslow")

        print("🧪 Running all tests...")
        return subprocess.run(cmd, cwd=self.project_root).returncode

    def run_fast_tests(self, verbose: bool = False) -> int:
        """Run fast tests (unit + integration)."""
        cmd = ["uv", "run", "pytest", "-m", "unit or integration", "--tb=short"]
        if verbose:
            cmd.append("-v")

        print("⚡ Running fast tests...")
        return subprocess.run(cmd, cwd=self.project_root).returncode

    def run_coverage_tests(self, verbose: bool = False) -> int:
        """Run tests with coverage reporting."""
        cmd = [
            "uv",
            "run",
            "pytest",
            "--cov=src/api",
            "--cov-report=html",
            "--cov-report=term-missing",
            "--tb=short",
        ]
        if verbose:
            cmd.append("-v")

        print("📊 Running tests with coverage...")
        return subprocess.run(cmd, cwd=self.project_root).returncode

    def run_performance_profile(self) -> int:
        """Run performance profiling."""
        print("📈 Running performance profile...")

        # Run zoom performance test
        cmd = ["uv", "run", "python", "tests/performance/test_zoom_performance.py"]
        result = subprocess.run(cmd, cwd=self.project_root)

        if result.returncode == 0:
            # Run load test
            cmd = ["uv", "run", "python", "tests/performance/simple_load_test.py"]
            result = subprocess.run(cmd, cwd=self.project_root)

        return result.returncode

    def check_test_health(self) -> dict[str, Any]:
        """Check test suite health and report issues."""
        issues = []

        # Check for test files
        test_files = list(self.test_dir.rglob("test_*.py"))
        if len(test_files) == 0:
            issues.append("No test files found")

        # Check for conftest.py
        if not (self.test_dir / "conftest.py").exists():
            issues.append("No conftest.py found")

        # Check for pytest configuration
        if not (self.project_root / "pyproject.toml").exists():
            issues.append("No pyproject.toml found")

        # Check directory structure
        required_dirs = ["unit", "integration", "performance", "security"]
        for dir_name in required_dirs:
            if not (self.test_dir / dir_name).exists():
                issues.append(f"Missing {dir_name} test directory")

        return {
            "test_files": len(test_files),
            "issues": issues,
            "healthy": len(issues) == 0,
        }

    def print_test_summary(self):
        """Print test suite summary."""
        health = self.check_test_health()

        print("=" * 60)
        print("🧪 FLOODMAP TEST SUITE SUMMARY")
        print("=" * 60)
        print(f"Test files found: {health['test_files']}")
        print(
            f"Test suite health: {'✅ HEALTHY' if health['healthy'] else '❌ ISSUES FOUND'}"
        )

        if health["issues"]:
            print("\n⚠️  Issues:")
            for issue in health["issues"]:
                print(f"   - {issue}")

        print("\n📋 Available test categories:")
        print("   • unit        - Fast unit tests (< 1s each)")
        print("   • integration - Integration tests (requires services)")
        print("   • performance - Performance and load tests")
        print("   • security    - Security validation tests")
        print("   • e2e         - End-to-end browser tests")
        print("   • visual      - Visual regression tests")
        print("   • slow        - Slow/stress tests")

        print("\n⚡ Quick test modes:")
        print("   • fast        - unit + integration")
        print("   • all         - all tests (excludes slow)")
        print("   • coverage    - all tests with coverage report")
        print("   • profile     - performance profiling")

        print("\n🎯 Example usage:")
        print("   python tests/run_tests.py fast")
        print("   python tests/run_tests.py performance --verbose")
        print("   python tests/run_tests.py all --coverage")
        print("=" * 60)


def main():
    """Main test runner."""
    parser = argparse.ArgumentParser(description="FloodMap Test Runner")
    parser.add_argument(
        "mode",
        choices=[
            "unit",
            "integration",
            "performance",
            "security",
            "e2e",
            "visual",
            "slow",
            "all",
            "fast",
            "coverage",
            "profile",
        ],
        help="Test mode to run",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument(
        "--include-slow", action="store_true", help="Include slow tests in 'all' mode"
    )

    args = parser.parse_args()

    runner = TestRunner()

    # Print summary if no mode specified
    if len(sys.argv) == 1:
        runner.print_test_summary()
        return 0

    # Run selected test mode
    start_time = time.time()

    if args.mode == "unit":
        result = runner.run_unit_tests(args.verbose)
    elif args.mode == "integration":
        result = runner.run_integration_tests(args.verbose)
    elif args.mode == "performance":
        result = runner.run_performance_tests(args.verbose)
    elif args.mode == "security":
        result = runner.run_security_tests(args.verbose)
    elif args.mode == "e2e":
        result = runner.run_e2e_tests(args.verbose)
    elif args.mode == "visual":
        result = runner.run_visual_tests(args.verbose)
    elif args.mode == "slow":
        result = runner.run_slow_tests(args.verbose)
    elif args.mode == "all":
        result = runner.run_all_tests(args.verbose, args.include_slow)
    elif args.mode == "fast":
        result = runner.run_fast_tests(args.verbose)
    elif args.mode == "coverage":
        result = runner.run_coverage_tests(args.verbose)
    elif args.mode == "profile":
        result = runner.run_performance_profile()
    else:
        print(f"Unknown mode: {args.mode}")
        return 1

    end_time = time.time()
    duration = end_time - start_time

    print(f"\n⏱️  Test run completed in {duration:.1f}s")
    print(f"Result: {'✅ PASSED' if result == 0 else '❌ FAILED'}")

    return result


if __name__ == "__main__":
    sys.exit(main())
