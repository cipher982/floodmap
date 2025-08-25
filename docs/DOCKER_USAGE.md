# Docker Usage Guide

## 🐳 **Single docker-compose.yml for All Environments**

We use one `docker-compose.yml` file with environment variables to handle both local development and production deployment.

## 🚀 **Quick Start**

### **Local Development**
```bash
# Add to your existing .env file (don't overwrite!)
echo "API_EXTERNAL_PORT=8000" >> .env
echo "TILESERVER_PORT=8080" >> .env
echo "ENVIRONMENT=development" >> .env

# Start services
docker compose up --build

# Test endpoints
curl http://localhost:8000/api/health
curl http://localhost:8080  # Tileserver UI
```

### **Production Deployment**  
```bash
# Add to your existing .env file (don't overwrite!)
echo "ENVIRONMENT=production" >> .env
echo "ELEVATION_DATA_PATH=/data/floodmap/elevation" >> .env
# Leave API_EXTERNAL_PORT unset for reverse proxy

# Deploy (no external ports - for reverse proxy)
docker compose up --build -d
```

## ⚙️ **Environment Configuration**

### **Key Environment Variables**

| Variable | Local Dev | Production | Purpose |
|----------|-----------|------------|---------|
| `API_EXTERNAL_PORT` | `8000` | *(empty)* | Expose API port externally |
| `TILESERVER_PORT` | `8080` | *(empty)* | Expose tileserver port |
| `ELEVATION_DATA_PATH` | `./output/elevation` | `/data/floodmap/elevation` | Elevation data location |
| `ENVIRONMENT` | `development` | `production` | Runtime environment |
| `MEMORY_LIMIT` | `1G` | `4G` | Container memory limit |

### **Port Behavior**
- **With ports set**: `API_EXTERNAL_PORT=8000` → Accessible on `localhost:8000`
- **Without ports**: `API_EXTERNAL_PORT=` → Internal only (reverse proxy access)

## 📋 **Common Commands**

### **Development Workflow**
```bash
# Ensure your .env has local development settings
# (Check .env.local for reference, but add to your existing .env)

# Start development environment
docker compose up --build

# View logs
docker compose logs -f api

# Rebuild after code changes
docker compose build api && docker compose up -d api

# Stop services
docker compose down
```

### **Production Workflow**
```bash
# Deploy data first
sudo ./deploy/data-sync.sh

# Ensure your .env has production settings
# (Check .env.production for reference, but add to your existing .env)

# Start production services
docker compose up --build -d

# Check health
docker compose exec api curl http://localhost:8000/api/health

# View logs
docker compose logs -f

# Update deployment
docker compose build && docker compose up -d
```

### **Troubleshooting**
```bash
# Check container status
docker compose ps

# Inspect specific service
docker compose logs api
docker compose exec api bash

# Check data mount
docker compose exec api ls -la /app/output/elevation/ | head -5

# Restart services
docker compose restart

# Clean rebuild
docker compose down && docker compose up --build
```

## 🔧 **Customization**

### **For Different VPS Setups**
```bash
# Large VPS (8GB+ RAM)
MEMORY_LIMIT=6G
ELEVATION_CACHE_SIZE=400
TILE_CACHE_SIZE=10000

# Small VPS (2GB RAM)  
MEMORY_LIMIT=1G
ELEVATION_CACHE_SIZE=50
TILE_CACHE_SIZE=1000

# High traffic
CPU_LIMIT=4.0
TILE_CACHE_SIZE=20000
```

### **For Different Data Locations**
```bash
# Network storage
ELEVATION_DATA_PATH=/mnt/nfs/floodmap/elevation

# Docker volume
ELEVATION_DATA_PATH=/var/lib/docker/volumes/elevation-data/_data

# Local SSD
ELEVATION_DATA_PATH=/fast-ssd/elevation
```

## 🏗️ **Architecture Summary**

**Single Compose File Benefits:**
- ✅ One file to maintain
- ✅ Environment-driven configuration
- ✅ Works for local dev and production
- ✅ Clear documentation in .env files
- ✅ No confusion about which file to use

**Service Communication:**
- `api` → `tileserver` (internal Docker network)
- External access via environment-controlled port mapping
- Reverse proxy routes to internal services when ports are disabled