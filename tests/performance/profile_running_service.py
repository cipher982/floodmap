#!/usr/bin/env python3
"""
Profile a running uvicorn service - attaches to existing process
"""
import subprocess
import time
import psutil
import requests
import sys
from pathlib import Path

def find_uvicorn_process():
    """Find running uvicorn process."""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if 'uvicorn' in proc.info['name'] or any('uvicorn' in arg for arg in proc.info['cmdline']):
                if any('main:app' in arg for arg in proc.info['cmdline']):
                    return proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None

def profile_with_load(pid: int, base_url: str, duration: int = 30):
    """Profile the service while generating load."""
    print(f"🔬 Profiling PID {pid} for {duration} seconds...")
    
    # Start py-spy profiling
    flamegraph_path = "/tmp/flood_map_flamegraph.svg"
    profile_cmd = [
        "py-spy", "record", 
        "-p", str(pid),
        "-d", str(duration),
        "-o", flamegraph_path,
        "--format", "flamegraph"
    ]
    
    print(f"Starting profiler: {' '.join(profile_cmd)}")
    profile_process = subprocess.Popen(profile_cmd)
    
    # Wait a moment for profiler to attach
    time.sleep(2)
    
    # Generate load while profiling
    print("🚀 Generating load...")
    load_requests = []
    
    # Test different tile coordinates to exercise the system
    tile_coords = [
        (11, 555, 859),  # Tampa area
        (11, 556, 859),
        (11, 555, 860),
        (12, 1110, 1718), # Higher zoom
        (10, 277, 429),   # Different area
    ]
    
    water_levels = [1.0, 2.0, 3.0, 4.0, 5.0]
    
    start_time = time.time()
    request_count = 0
    
    while time.time() - start_time < duration - 5:  # Stop 5s before profiler
        for z, x, y in tile_coords:
            for water_level in water_levels:
                try:
                    url = f"{base_url}/api/v1/tiles/elevation-data/{z}/{x}/{y}.u16"
                    start_req = time.perf_counter()
                    response = requests.get(url, timeout=10)
                    end_req = time.perf_counter()
                    
                    load_requests.append({
                        "url": url,
                        "duration_ms": (end_req - start_req) * 1000,
                        "status": response.status_code,
                        "size": len(response.content) if response.content else 0
                    })
                    request_count += 1
                    
                    if request_count % 10 == 0:
                        print(f"  Sent {request_count} requests...")
                    
                    # Small delay to avoid overwhelming
                    time.sleep(0.1)
                    
                except Exception as e:
                    print(f"Request failed: {e}")
                    
                # Check if we should stop
                if time.time() - start_time >= duration - 5:
                    break
            
            if time.time() - start_time >= duration - 5:
                break
    
    print(f"🏁 Sent {request_count} requests, waiting for profiler to finish...")
    
    # Wait for profiler to complete
    profile_process.wait()
    
    # Analyze load test results
    if load_requests:
        successful = [r for r in load_requests if r["status"] == 200]
        if successful:
            import statistics
            durations = [r["duration_ms"] for r in successful]
            
            print(f"\\n📊 LOAD TEST RESULTS DURING PROFILING")
            print(f"─" * 50)
            print(f"Total Requests:    {len(load_requests)}")
            print(f"Successful:        {len(successful)} ({len(successful)/len(load_requests)*100:.1f}%)")
            print(f"Average Duration:  {statistics.mean(durations):.1f} ms")
            print(f"95th Percentile:   {statistics.quantiles(durations, n=20)[18]:.1f} ms")
            print(f"Min/Max:           {min(durations):.1f} / {max(durations):.1f} ms")
    
    # Check if flamegraph was created
    if Path(flamegraph_path).exists():
        print(f"\\n🔥 Flamegraph created: {flamegraph_path}")
        print(f"Open with: open {flamegraph_path}")
        return flamegraph_path
    else:
        print("❌ Flamegraph not created - check py-spy permissions")
        return None

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Profile running flood map service')
    parser.add_argument('--url', default='http://localhost:5002', help='Base URL')
    parser.add_argument('--duration', type=int, default=30, help='Profile duration in seconds')
    
    args = parser.parse_args()
    
    # Check if service is running
    try:
        response = requests.get(f"{args.url}/api/health", timeout=5)
        if response.status_code != 200:
            print(f"❌ Service not healthy at {args.url}")
            return 1
    except Exception as e:
        print(f"❌ Cannot connect to {args.url}: {e}")
        return 1
    
    # Find the uvicorn process
    pid = find_uvicorn_process()
    if not pid:
        print("❌ Could not find running uvicorn process")
        print("Make sure the service is running with: make start")
        return 1
    
    print(f"✅ Found uvicorn process: PID {pid}")
    
    # Profile it
    flamegraph_path = profile_with_load(pid, args.url, args.duration)
    
    if flamegraph_path:
        print(f"\\n🎯 Next steps:")
        print(f"1. Open flamegraph: open {flamegraph_path}")
        print(f"2. Look for the hottest paths (widest red bars)")
        print(f"3. Identify the biggest bottlenecks")
        return 0
    else:
        return 1

if __name__ == "__main__":
    exit(main())
