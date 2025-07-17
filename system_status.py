#!/usr/bin/env python3
"""
Comprehensive system status monitor for flood map infrastructure.
Shows download progress, API health, tile availability, and system resources.
"""

import requests
import json
import time
import os
import subprocess
from pathlib import Path
from datetime import datetime
import psutil


class FloodMapSystemMonitor:
    """Monitor all aspects of the flood map system."""
    
    def __init__(self):
        self.api_base_url = "http://localhost:5002"
        self.base_dir = Path("/Users/davidrose/git/floodmap")
        
    def check_api_health(self) -> dict:
        """Check API health and metrics."""
        try:
            health_response = requests.get(f"{self.api_base_url}/api/health", timeout=5)
            health_data = health_response.json() if health_response.status_code == 200 else {"status": "unreachable"}
            
            try:
                metrics_response = requests.get(f"{self.api_base_url}/api/metrics", timeout=5)
                metrics_data = metrics_response.json() if metrics_response.status_code == 200 else {}
            except:
                metrics_data = {}
            
            return {
                "health": health_data,
                "metrics": metrics_data,
                "api_accessible": health_response.status_code == 200
            }
        except Exception as e:
            return {
                "health": {"status": "unreachable", "error": str(e)},
                "metrics": {},
                "api_accessible": False
            }
    
    def check_elevation_data(self) -> dict:
        """Check elevation data availability."""
        elevation_dir = self.base_dir / "compressed_data" / "usa"
        
        if not elevation_dir.exists():
            return {"available": False, "file_count": 0, "total_size_gb": 0}
        
        files = list(elevation_dir.glob("*.zst"))
        total_size = sum(f.stat().st_size for f in files)
        
        return {
            "available": len(files) > 0,
            "file_count": len(files),
            "total_size_gb": total_size / (1024**3),
            "directory": str(elevation_dir)
        }
    
    def check_map_data(self) -> dict:
        """Check map tile data availability."""
        map_data_dir = self.base_dir / "map_data"
        regions_dir = map_data_dir / "regions"
        
        result = {
            "main_tiles": [],
            "regional_tiles": [],
            "total_size_gb": 0
        }
        
        # Check main map data
        if map_data_dir.exists():
            for mbtiles_file in map_data_dir.glob("*.mbtiles"):
                size_mb = mbtiles_file.stat().st_size / (1024**2)
                result["main_tiles"].append({
                    "name": mbtiles_file.name,
                    "size_mb": size_mb,
                    "modified": datetime.fromtimestamp(mbtiles_file.stat().st_mtime).isoformat()
                })
                result["total_size_gb"] += size_mb / 1024
        
        # Check regional map data
        if regions_dir.exists():
            for mbtiles_file in regions_dir.glob("*.mbtiles"):
                size_mb = mbtiles_file.stat().st_size / (1024**2)
                result["regional_tiles"].append({
                    "name": mbtiles_file.name,
                    "size_mb": size_mb,
                    "modified": datetime.fromtimestamp(mbtiles_file.stat().st_mtime).isoformat()
                })
                result["total_size_gb"] += size_mb / 1024
        
        return result
    
    def check_download_progress(self) -> dict:
        """Check progress of ongoing downloads."""
        progress = {}
        
        # Check California download
        ca_log = Path("/tmp/ca_download.log")
        if ca_log.exists():
            try:
                with open(ca_log, 'r') as f:
                    lines = f.readlines()
                
                # Find latest progress line
                for line in reversed(lines):
                    if "California:" in line and "%" in line:
                        # Extract percentage
                        if "%" in line:
                            percent_str = line.split("%")[0].split()[-1]
                            try:
                                progress["california"] = {
                                    "status": "downloading",
                                    "progress_percent": float(percent_str),
                                    "latest_line": line.strip()
                                }
                            except:
                                pass
                        break
                        
                # Check if completed
                if any("✅" in line and "California" in line for line in lines[-10:]):
                    progress["california"]["status"] = "completed"
                    
            except Exception as e:
                progress["california"] = {"status": "error", "error": str(e)}
        
        # Check New York download
        ny_log = Path("/tmp/ny_download.log")
        if ny_log.exists():
            try:
                with open(ny_log, 'r') as f:
                    lines = f.readlines()
                
                # Find latest progress line
                for line in reversed(lines):
                    if "New York:" in line and "%" in line:
                        # Extract percentage
                        if "%" in line:
                            percent_str = line.split("%")[0].split()[-1]
                            try:
                                progress["new_york"] = {
                                    "status": "downloading",
                                    "progress_percent": float(percent_str),
                                    "latest_line": line.strip()
                                }
                            except:
                                pass
                        break
                        
                # Check if completed
                if any("✅" in line and "New York" in line for line in lines[-10:]):
                    progress["new_york"]["status"] = "completed"
                    
            except Exception as e:
                progress["new_york"] = {"status": "error", "error": str(e)}
        
        return progress
    
    def check_system_resources(self) -> dict:
        """Check system resource usage."""
        try:
            return {
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_usage": {
                    "total_gb": psutil.disk_usage('/').total / (1024**3),
                    "used_gb": psutil.disk_usage('/').used / (1024**3),
                    "free_gb": psutil.disk_usage('/').free / (1024**3)
                },
                "load_average": os.getloadavg() if hasattr(os, 'getloadavg') else [0, 0, 0]
            }
        except Exception as e:
            return {"error": str(e)}
    
    def check_running_processes(self) -> dict:
        """Check key running processes."""
        processes = {}
        
        try:
            # Check for uvicorn (API server)
            uvicorn_procs = [p for p in psutil.process_iter(['pid', 'name', 'cmdline']) 
                           if p.info['name'] and 'uvicorn' in p.info['name']]
            processes["api_server"] = {
                "running": len(uvicorn_procs) > 0,
                "count": len(uvicorn_procs),
                "pids": [p.info['pid'] for p in uvicorn_procs]
            }
            
            # Check for docker (tileserver)
            docker_procs = [p for p in psutil.process_iter(['pid', 'name', 'cmdline'])
                          if p.info['cmdline'] and any('tileserver' in str(cmd) for cmd in p.info['cmdline'])]
            processes["tileserver"] = {
                "running": len(docker_procs) > 0,
                "count": len(docker_procs),
                "pids": [p.info['pid'] for p in docker_procs]
            }
            
            # Check for download processes
            download_procs = [p for p in psutil.process_iter(['pid', 'name', 'cmdline'])
                            if p.info['cmdline'] and any('download_regional_maps' in str(cmd) for cmd in p.info['cmdline'])]
            processes["downloads"] = {
                "running": len(download_procs) > 0,
                "count": len(download_procs),
                "pids": [p.info['pid'] for p in download_procs]
            }
            
        except Exception as e:
            processes["error"] = str(e)
        
        return processes
    
    def generate_report(self) -> dict:
        """Generate comprehensive system report."""
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "api": self.check_api_health(),
            "elevation_data": self.check_elevation_data(),
            "map_data": self.check_map_data(),
            "downloads": self.check_download_progress(),
            "system": self.check_system_resources(),
            "processes": self.check_running_processes()
        }
        
        return report
    
    def print_status(self):
        """Print formatted status report."""
        report = self.generate_report()
        
        print("🌊 FLOOD MAP SYSTEM STATUS")
        print("=" * 50)
        print(f"📅 {report['timestamp']}")
        print()
        
        # API Status
        api = report['api']
        api_status = "🟢" if api['api_accessible'] else "🔴"
        print(f"{api_status} API Server: {api['health'].get('status', 'unknown')}")
        if api.get('metrics'):
            metrics = api['metrics']
            print(f"   Requests: {metrics.get('tile_requests', 0)}")
            print(f"   Cache Hit Rate: {metrics.get('cache_hit_rate', 0):.1%}")
            print(f"   Error Rate: {metrics.get('error_rate', 0):.1%}")
        print()
        
        # Elevation Data
        elevation = report['elevation_data']
        elev_status = "🟢" if elevation['available'] else "🔴"
        print(f"{elev_status} Elevation Data: {elevation['file_count']} files ({elevation['total_size_gb']:.1f}GB)")
        print()
        
        # Map Data
        map_data = report['map_data']
        total_tiles = len(map_data['main_tiles']) + len(map_data['regional_tiles'])
        map_status = "🟢" if total_tiles > 0 else "🔴"
        print(f"{map_status} Map Tiles: {total_tiles} files ({map_data['total_size_gb']:.1f}GB)")
        for tile in map_data['main_tiles']:
            print(f"   📍 {tile['name']}: {tile['size_mb']:.1f}MB")
        for tile in map_data['regional_tiles']:
            print(f"   🗺️  {tile['name']}: {tile['size_mb']:.1f}MB")
        print()
        
        # Downloads
        downloads = report['downloads']
        if downloads:
            print("📥 Active Downloads:")
            for region, status in downloads.items():
                if status.get('status') == 'downloading':
                    print(f"   {region}: {status['progress_percent']:.1f}%")
                elif status.get('status') == 'completed':
                    print(f"   {region}: ✅ Completed")
                elif status.get('status') == 'error':
                    print(f"   {region}: ❌ Error")
            print()
        
        # System Resources
        system = report['system']
        if 'error' not in system:
            cpu_status = "🔴" if system['cpu_percent'] > 80 else "🟡" if system['cpu_percent'] > 50 else "🟢"
            mem_status = "🔴" if system['memory_percent'] > 80 else "🟡" if system['memory_percent'] > 60 else "🟢"
            disk_usage_percent = (system['disk_usage']['used_gb'] / system['disk_usage']['total_gb']) * 100
            disk_status = "🔴" if disk_usage_percent > 90 else "🟡" if disk_usage_percent > 75 else "🟢"
            
            print("💻 System Resources:")
            print(f"   {cpu_status} CPU: {system['cpu_percent']:.1f}%")
            print(f"   {mem_status} Memory: {system['memory_percent']:.1f}%")
            print(f"   {disk_status} Disk: {disk_usage_percent:.1f}% ({system['disk_usage']['free_gb']:.1f}GB free)")
            print(f"   Load: {system['load_average'][0]:.2f}, {system['load_average'][1]:.2f}, {system['load_average'][2]:.2f}")
            print()
        
        # Running Processes
        processes = report['processes']
        if 'error' not in processes:
            print("🔄 Running Processes:")
            for proc_type, info in processes.items():
                status = "🟢" if info['running'] else "🔴"
                print(f"   {status} {proc_type}: {info['count']} running")
            print()
        
        # Overall Health
        overall_healthy = (
            api['api_accessible'] and
            elevation['available'] and
            total_tiles > 0 and
            system.get('cpu_percent', 0) < 90 and
            system.get('memory_percent', 0) < 90
        )
        
        overall_status = "🟢 HEALTHY" if overall_healthy else "🟡 DEGRADED"
        print(f"🎯 Overall Status: {overall_status}")


def main():
    """Main monitoring function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Monitor flood map system status")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of formatted text")
    parser.add_argument("--watch", type=int, help="Watch mode - refresh every N seconds")
    
    args = parser.parse_args()
    
    monitor = FloodMapSystemMonitor()
    
    if args.watch:
        try:
            while True:
                if not args.json:
                    os.system('clear')  # Clear screen
                
                if args.json:
                    print(json.dumps(monitor.generate_report(), indent=2))
                else:
                    monitor.print_status()
                
                if args.watch:
                    time.sleep(args.watch)
                else:
                    break
        except KeyboardInterrupt:
            print("\n👋 Monitoring stopped")
    else:
        if args.json:
            print(json.dumps(monitor.generate_report(), indent=2))
        else:
            monitor.print_status()


if __name__ == "__main__":
    main()