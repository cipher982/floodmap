#!/usr/bin/env python3
"""
Comprehensive test to validate the current working elevation overlay state.
This test locks in our current working configuration.
"""

import requests
import subprocess
import time
import sys


def test_services_running():
    """Test that required services are running."""
    print("🔍 Testing services...")
    
    # Test tileserver
    try:
        response = requests.get("http://localhost:8080", timeout=5)
        print("✅ Tileserver running")
    except requests.RequestException:
        print("❌ Tileserver not running - run 'make start' first")
        return False
    
    # Test new architecture website
    try:
        response = requests.get("http://localhost:5002", timeout=5)
        print("✅ New architecture website running")
    except requests.RequestException:
        print("❌ New architecture website not running - run 'make start' first")
        return False
    
    return True


def test_elevation_tiles():
    """Test that elevation tiles are working."""
    print("\n🏔️  Testing elevation tiles...")
    
    # Test specific tiles that should exist
    test_tiles = [
        (12, 1103, 1709),
        (12, 1103, 1708),
        (12, 1102, 1709),
        (11, 551, 854),
        (10, 275, 427)
    ]
    
    working_tiles = 0
    for z, x, y in test_tiles:
        url = f"http://localhost:5002/api/tiles/elevation/{z}/{x}/{y}.png"
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200 and response.headers.get('content-type') == 'image/png':
                working_tiles += 1
                print(f"✅ Tile {z}/{x}/{y} - {len(response.content)} bytes")
            else:
                print(f"❌ Tile {z}/{x}/{y} - Status: {response.status_code}")
        except requests.RequestException as e:
            print(f"❌ Tile {z}/{x}/{y} - Error: {e}")
    
    success_rate = working_tiles / len(test_tiles)
    print(f"\n📊 Elevation tiles: {working_tiles}/{len(test_tiles)} working ({success_rate:.1%})")
    
    return success_rate > 0.8  # Require 80% success rate


def test_api_endpoints():
    """Test core API endpoints."""
    print("\n🔌 Testing API endpoints...")
    
    endpoints = [
        ("/api/health", "Health check"),
        ("/api/tiles/vector/11/551/854.pbf", "Vector tiles"),
    ]
    
    working_endpoints = 0
    for endpoint, description in endpoints:
        url = f"http://localhost:5002{endpoint}"
        try:
            response = requests.get(url, timeout=5)
            if response.status_code in [200, 204]:  # 204 for empty tiles
                working_endpoints += 1
                print(f"✅ {description} - Status: {response.status_code}")
            else:
                print(f"❌ {description} - Status: {response.status_code}")
        except requests.RequestException as e:
            print(f"❌ {description} - Error: {e}")
    
    success_rate = working_endpoints / len(endpoints)
    print(f"\n📊 API endpoints: {working_endpoints}/{len(endpoints)} working ({success_rate:.1%})")
    
    return success_rate > 0.8


def test_makefile_commands():
    """Test that Makefile commands work as expected."""
    print("\n⚙️  Testing Makefile commands...")
    
    # Test make test
    try:
        result = subprocess.run(['make', 'test'], capture_output=True, text=True, timeout=30)
        if "✅ Website responds" in result.stdout and "✅ Elevation tiles work" in result.stdout:
            print("✅ 'make test' passes")
            return True
        else:
            print(f"❌ 'make test' failed: {result.stdout}")
            return False
    except subprocess.TimeoutExpired:
        print("❌ 'make test' timed out")
        return False
    except Exception as e:
        print(f"❌ 'make test' error: {e}")
        return False


def main():
    """Run all tests to validate working state."""
    print("🌊 FLOOD MAP - WORKING STATE VALIDATION")
    print("=" * 50)
    
    tests = [
        ("Services Running", test_services_running),
        ("Elevation Tiles", test_elevation_tiles),
        ("API Endpoints", test_api_endpoints),
        ("Makefile Commands", test_makefile_commands)
    ]
    
    passed = 0
    for test_name, test_func in tests:
        print(f"\n🧪 Running: {test_name}")
        if test_func():
            passed += 1
            print(f"✅ {test_name} - PASSED")
        else:
            print(f"❌ {test_name} - FAILED")
    
    success_rate = passed / len(tests)
    print(f"\n" + "=" * 50)
    print(f"🎯 FINAL RESULT: {passed}/{len(tests)} tests passed ({success_rate:.1%})")
    
    if success_rate == 1.0:
        print("🎉 ALL TESTS PASSED - Working state confirmed!")
        print("📌 Elevation overlays are working correctly")
        print("🚀 Ready for production!")
        return 0
    else:
        print("⚠️  Some tests failed - check output above")
        print("💡 Make sure to run 'make start' first")
        return 1


if __name__ == "__main__":
    sys.exit(main())