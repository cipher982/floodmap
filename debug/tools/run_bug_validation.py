#!/usr/bin/env python3
"""
Master script to run all tile discontinuity validation tests.
"""

import subprocess
import sys
import time
from pathlib import Path

import requests


def check_server():
    """Check if the flood map server is running."""
    try:
        response = requests.get("http://localhost:8000/api/health", timeout=3)
        return response.status_code == 200
    except:
        return False


def run_test_script(script_name):
    """Run a test script and capture its output."""
    print(f"\n{'=' * 60}")
    print(f"🧪 RUNNING: {script_name}")
    print(f"{'=' * 60}")

    try:
        result = subprocess.run(
            [sys.executable, script_name], capture_output=True, text=True, timeout=120
        )

        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)

        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"❌ {script_name} timed out after 2 minutes")
        return False
    except Exception as e:
        print(f"❌ Error running {script_name}: {e}")
        return False


def main():
    print("🌊 Flood Map Bug Validation Suite")
    print("=" * 60)

    # Check if we're in the right directory
    if not Path("src/api").exists():
        print("❌ Please run this from the floodmap project root directory")
        sys.exit(1)

    # Check if server is running
    if not check_server():
        print("❌ Server is not running at localhost:8000")
        print("\nTo start the server, run:")
        print("  cd /Users/davidrose/git/floodmap")
        print("  make start")
        print("\nOr manually:")
        print("  cd src && uv run python -m api.main")

        # Ask if user wants to continue with offline tests only
        response = input("\nRun offline tests only? (y/n): ").lower().strip()
        if response != "y":
            sys.exit(1)

        server_running = False
    else:
        print("✅ Server is running")
        server_running = True

    # Run the tests
    results = {}

    if server_running:
        print("\n🌐 Running online tests (require server)...")
        results["tile_boundary"] = run_test_script("debug_tile_discontinuity.py")
        time.sleep(2)  # Give server a break

    print("\n💻 Running offline tests...")
    results["elevation_consistency"] = run_test_script("debug_elevation_consistency.py")

    # Summary
    print("\n" + "=" * 60)
    print("📊 BUG VALIDATION SUMMARY")
    print("=" * 60)

    total_tests = 0
    passed_tests = 0

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "🚨 FAIL"
        print(f"{test_name:20}: {status}")
        total_tests += 1
        if passed:
            passed_tests += 1

    print(f"\nOverall: {passed_tests}/{total_tests} test suites passed")

    # Check for generated files
    generated_files = []
    for filename in [
        "tile_boundary_debug.png",
        "tile_boundary_analysis.png",
        "elevation_consistency_analysis.png",
    ]:
        if Path(filename).exists():
            generated_files.append(filename)

    if generated_files:
        print("\n📁 Generated debug files:")
        for f in generated_files:
            print(f"   {f}")
        print("\n💡 Open these images to visually inspect the tile discontinuities")

    if passed_tests < total_tests:
        print("\n🚨 BUG VALIDATION: Issues detected!")
        print("   Use the generated files and test output to identify root causes")
    else:
        print("\n✅ BUG VALIDATION: No obvious issues detected")
        print("   The problem may be more subtle or in different coordinates")

    print("\n📖 Next steps:")
    if not server_running:
        print("   1. Start the server and run online tests")
    print("   2. Examine the generated visualization files")
    print("   3. Try different coordinates if no issues found")
    print("   4. Check the test output for specific inconsistencies")


if __name__ == "__main__":
    main()
