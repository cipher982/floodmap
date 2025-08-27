#!/usr/bin/env python3
"""
Simple load test for elevation tiles - no external dependencies
"""
import requests
import time
import threading
import statistics
from concurrent.futures import ThreadPoolExecutor
import json

def single_tile_request(url: str, timeout: int = 10) -> dict:
    """Make a single tile request and measure timing."""
    start_time = time.perf_counter()
    try:
        response = requests.get(url, timeout=timeout)
        end_time = time.perf_counter()
        
        return {
            "duration_ms": (end_time - start_time) * 1000,
            "status_code": response.status_code,
            "content_length": len(response.content) if response.content else 0,
            "cache_hit": response.headers.get('X-Cache') == 'HIT',
            "error": None
        }
    except Exception as e:
        end_time = time.perf_counter()
        return {
            "duration_ms": (end_time - start_time) * 1000,
            "status_code": 0,
            "content_length": 0,
            "cache_hit": False,
            "error": str(e)
        }

def concurrent_load_test(base_url: str, concurrent_users: int = 10, duration_seconds: int = 30):
    """Run concurrent load test similar to wrk."""
    print(f"🚀 Running load test: {concurrent_users} concurrent users for {duration_seconds}s")
    print(f"Target: {base_url}")
    
    results = []
    start_time = time.time()
    end_time = start_time + duration_seconds
    
    # Test different tiles to avoid excessive caching
    tile_urls = [
        f"{base_url}/api/v1/tiles/elevation-data/11/{555+i}/{859+j}.u16"
        for i in range(-2, 3) for j in range(-2, 3)
    ]
    
    def worker():
        """Worker thread that keeps making requests."""
        tile_index = 0
        while time.time() < end_time:
            url = tile_urls[tile_index % len(tile_urls)]
            result = single_tile_request(url)
            results.append(result)
            tile_index += 1
            
            # Small delay to avoid overwhelming
            time.sleep(0.1)
    
    # Start concurrent workers
    with ThreadPoolExecutor(max_workers=concurrent_users) as executor:
        futures = [executor.submit(worker) for _ in range(concurrent_users)]
        
        # Wait for all workers to complete
        for future in futures:
            future.result()
    
    # Analyze results
    successful_requests = [r for r in results if r["status_code"] == 200]
    failed_requests = [r for r in results if r["status_code"] != 200]
    
    if successful_requests:
        durations = [r["duration_ms"] for r in successful_requests]
        
        print(f"\\n📊 LOAD TEST RESULTS")
        print(f"─" * 40)
        print(f"Total Requests:     {len(results)}")
        print(f"Successful:         {len(successful_requests)} ({len(successful_requests)/len(results)*100:.1f}%)")
        print(f"Failed:             {len(failed_requests)}")
        print(f"Requests/sec:       {len(results)/duration_seconds:.1f}")
        print(f"")
        print(f"Response Times:")
        print(f"  Average:          {statistics.mean(durations):.1f} ms")
        print(f"  Median:           {statistics.median(durations):.1f} ms")
        print(f"  95th percentile:  {statistics.quantiles(durations, n=20)[18]:.1f} ms")
        print(f"  Min:              {min(durations):.1f} ms")
        print(f"  Max:              {max(durations):.1f} ms")
        
        cache_hits = sum(1 for r in successful_requests if r["cache_hit"])
        print(f"Cache Hit Rate:     {cache_hits/len(successful_requests)*100:.1f}%")
        
        # Performance assessment
        avg_duration = statistics.mean(durations)
        if avg_duration < 100:
            print(f"🟢 Performance: EXCELLENT (<100ms)")
        elif avg_duration < 300:
            print(f"🟡 Performance: ACCEPTABLE (100-300ms)")
        else:
            print(f"🔴 Performance: NEEDS OPTIMIZATION (>300ms)")
        
        # Show error breakdown
        if failed_requests:
            print(f"\\n❌ Error Breakdown:")
            error_counts = {}
            for r in failed_requests:
                error_key = f"{r['status_code']}: {r['error']}" if r['error'] else f"HTTP {r['status_code']}"
                error_counts[error_key] = error_counts.get(error_key, 0) + 1
            
            for error, count in error_counts.items():
                print(f"  {error}: {count}")
    
    else:
        print("❌ No successful requests!")
        
    return results

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Simple load test for flood map tiles')
    parser.add_argument('--url', default='http://localhost:5002', help='Base URL')
    parser.add_argument('--concurrent', type=int, default=10, help='Concurrent users')
    parser.add_argument('--duration', type=int, default=30, help='Test duration in seconds')
    parser.add_argument('--output', help='Save results to JSON file')
    
    args = parser.parse_args()
    
    # Test connectivity first
    try:
        response = requests.get(f"{args.url}/api/health", timeout=5)
        if response.status_code != 200:
            print(f"❌ Service not healthy at {args.url}")
            return 1
    except Exception as e:
        print(f"❌ Cannot connect to {args.url}: {e}")
        return 1
    
    print(f"✅ Service is healthy at {args.url}")
    
    # Run load test
    results = concurrent_load_test(args.url, args.concurrent, args.duration)
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\\n📄 Results saved to {args.output}")
    
    return 0

if __name__ == "__main__":
    exit(main())
