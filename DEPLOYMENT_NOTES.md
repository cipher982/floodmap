# 🚀 Deployment Configuration Notes

## Critical Environment Variables

### ⚠️ **REQUIRED**: TileServer Configuration  

**Before deploying, ensure your `.env` or environment has:**

```bash
# TileServer Configuration (CRITICAL)
TILESERVER_PORT=8080                    # Must match Docker container port
TILESERVER_URL=http://127.0.0.1:8080   # API proxy target (use 127.0.0.1, not localhost)

# API Configuration  
API_PORT=60197                          # Your API server port

# Data Paths
ELEVATION_DATA_DIR=output/elevation     # Elevation tile data directory
PROJECT_ROOT=/path/to/your/project      # Project root path
```

## 🔧 Recent Changes (2025-01-21)

### Fixed Issues:
- ✅ **Vector tile 503 errors** during map dragging
- ✅ **Connection pool exhaustion** in httpx client
- ✅ **Port mismatch** between tileserver and API proxy

### Breaking Changes:
- **TILESERVER_URL must point to correct port** (8080, not 8081)
- **Use 127.0.0.1 instead of localhost** for Docker connectivity

## 🧪 Testing Checklist

After deployment:
1. ✅ Health endpoint: `curl http://your-domain/api/health`  
2. ✅ Elevation tiles: `curl http://your-domain/api/v1/tiles/elevation-data/8/68/106.u16`
3. ✅ Vector tiles: `curl http://your-domain/api/v1/tiles/vector/usa/8/68/106.pbf` 
4. ✅ **Map drag test**: Open map, drag rapidly - no 503 errors in browser console

## 🚨 Common Deployment Issues

### "503 Service Unavailable" on Vector Tiles
**Root Cause**: Wrong TILESERVER_URL port  
**Fix**: Ensure TILESERVER_URL matches your actual tileserver port

### "Connection refused" errors  
**Root Cause**: Using `localhost` instead of `127.0.0.1`  
**Fix**: Use `127.0.0.1` in TILESERVER_URL for Docker compatibility

### Map tiles load but dragging is "glitchy"
**Root Cause**: Vector tiles not loading (check browser console)  
**Fix**: Verify tileserver is running and accessible from API container