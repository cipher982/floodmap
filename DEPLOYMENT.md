# FloodMap VPS Deployment Guide

This guide covers deploying FloodMap to a VPS using Docker Compose with reverse proxy integration.

## 🏗️ Architecture Overview

- **API Server**: FastAPI application serving elevation tiles and flood risk data
- **Tile Server**: MapTiler GL server providing vector map tiles
- **Reverse Proxy**: Routes external traffic to internal Docker services (Coolify managed)
- **Data Volume**: 13GB of compressed elevation data (SRTM + 3DEP patches)

## 📋 Prerequisites

1. **VPS Requirements**:
   - 4+ GB RAM (recommended: 8GB for optimal caching)
   - 2+ CPU cores
   - 50+ GB disk space (20GB for data + 30GB for system/other apps)
   - Docker & Docker Compose installed

2. **Data Preparation**:
   - 13GB elevation data from local development environment
   - Vector map tiles (usa-complete.mbtiles)

## 🚀 Quick Deployment (Coolify)

### Step 1: Repository Setup
```bash
# Clone the repository
git clone <your-repo-url> floodmap
cd floodmap
```

### Step 2: Environment Configuration
```bash
# Copy and customize environment file
cp .env.example .env

# Key settings for production:
# ELEVATION_DATA_PATH=/data/floodmap/elevation
# ENVIRONMENT=production
# ELEVATION_CACHE_SIZE=200
# TILE_CACHE_SIZE=5000
```

### Step 3: Data Deployment

#### Option A: Direct File Transfer (Recommended)
```bash
# Create data directory
sudo mkdir -p /data/floodmap/elevation

# Copy elevation data from development machine
rsync -avh --progress user@dev-machine:/path/to/floodmap/output/elevation/ \
  /data/floodmap/elevation/

# Or use the deployment script
sudo ./deploy/data-sync.sh
```

#### Option B: Git LFS (If data is in LFS)
```bash
# Install Git LFS
git lfs install

# Pull LFS data
git lfs pull

# Run deployment script
sudo ./deploy/data-sync.sh
```

#### Option C: S3 Download (If using S3)
```bash
# Set AWS credentials in .env
aws s3 sync s3://your-bucket/elevation-data /data/floodmap/elevation
```

### Step 4: Deploy with Coolify

1. **Add New Service** in Coolify
2. **Use Docker Compose** deployment type
3. **Point to** `docker-compose.prod.yml`
4. **Set Environment Variables** from `.env`
5. **Configure Reverse Proxy**:
   - Service: `floodmap-api-prod`
   - Port: `8000`
   - Domain: `your-domain.com`

### Step 5: Verification
```bash
# Check container health
docker ps
docker logs floodmap-api-prod
docker logs floodmap-tileserver-prod

# Test API endpoints
curl https://your-domain.com/api/health
curl https://your-domain.com/api/elevation/tile/10/5/5.png
```

## 🔧 Manual Docker Compose Deployment

If not using Coolify:

```bash
# Start services
docker-compose -f docker-compose.prod.yml up -d

# Check logs
docker-compose -f docker-compose.prod.yml logs -f

# Scale API service
docker-compose -f docker-compose.prod.yml up -d --scale api=2
```

### Reverse Proxy Configuration (Nginx Example)
```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;
    
    ssl_certificate /path/to/ssl/cert.pem;
    ssl_certificate_key /path/to/ssl/key.pem;
    
    # API endpoints
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # Tile endpoints  
    location /v1/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        
        # Cache tiles aggressively
        proxy_cache_valid 200 7d;
        add_header X-Cache-Status $upstream_cache_status;
    }
    
    # Frontend
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 📊 Monitoring & Performance

### Health Checks
- API Health: `https://your-domain.com/api/health`
- Tile Server: Internal health checks via Docker

### Performance Tuning
```bash
# Increase cache sizes for better performance
ELEVATION_CACHE_SIZE=400    # For 8GB+ RAM
TILE_CACHE_SIZE=10000       # For frequent tile requests

# Resource limits (in docker-compose.prod.yml)
deploy:
  resources:
    limits:
      memory: 4G
      cpus: '2.0'
```

### Monitoring Integration
```bash
# Add to .env for observability
OTEL_EXPORTER_OTLP_ENDPOINT=https://your-monitoring.com/v1/traces
OTEL_EXPORTER_OTLP_HEADERS_AUTHORIZATION=Bearer your-token
```

## 🔒 Security Considerations

### Container Security
- ✅ Read-only elevation data mounts
- ✅ Non-root container execution
- ✅ No-new-privileges security option
- ✅ Limited tmpfs for temporary files
- ✅ Network isolation (no external ports)

### Data Security
- ✅ Elevation data is read-only (444 permissions)
- ✅ No sensitive data in environment variables
- ✅ Rate limiting enabled (120 req/min default)

### Network Security
- ✅ All services internal-only (reverse proxy access only)
- ✅ No direct container port exposure
- ✅ Isolated Docker network

## 🚨 Troubleshooting

### Common Issues

**1. Missing Elevation Data**
```bash
# Check data directory
ls -la /data/floodmap/elevation/
# Should show ~2,262 .zst files and .json metadata

# Verify deployment
./deploy/data-sync.sh --verify-only
```

**2. Container Won't Start**
```bash
# Check logs
docker logs floodmap-api-prod
docker logs floodmap-tileserver-prod

# Common issues:
# - Missing data volume
# - Permission issues  
# - Port conflicts
```

**3. Slow Tile Performance**
```bash
# Increase cache sizes in .env
ELEVATION_CACHE_SIZE=400
TILE_CACHE_SIZE=10000

# Check memory usage
docker stats floodmap-api-prod
```

**4. Reverse Proxy Issues**
```bash
# Verify container is accessible internally
docker exec -it floodmap-api-prod curl http://localhost:8000/api/health

# Check network connectivity
docker network ls
docker network inspect floodmap-prod-network
```

## 🔄 Updates & Maintenance

### Application Updates
```bash
# Pull latest changes
git pull origin main

# Rebuild and restart
docker-compose -f docker-compose.prod.yml build --no-cache
docker-compose -f docker-compose.prod.yml up -d
```

### Data Updates
```bash
# Update elevation data
./deploy/data-sync.sh

# Restart to clear caches
docker-compose -f docker-compose.prod.yml restart api
```

### Log Management
```bash
# View recent logs
docker-compose -f docker-compose.prod.yml logs --tail=100 -f

# Clean up old logs
docker system prune -f
```

## 📈 Scaling

For high-traffic deployments:

1. **Scale API service**:
   ```bash
   docker-compose -f docker-compose.prod.yml up -d --scale api=3
   ```

2. **Add external cache**:
   - Redis for tile caching
   - CDN for static assets

3. **Database for analytics**:
   - PostgreSQL for usage tracking
   - ClickHouse for telemetry

## 💡 Tips

- **Memory**: 8GB+ RAM recommended for optimal caching
- **Storage**: SSD strongly recommended for elevation data
- **Network**: Consider CDN for tile delivery
- **Monitoring**: Enable OpenTelemetry for production observability
- **Backups**: Regular backups of configuration and logs (elevation data is immutable)

---

## 🆘 Support

For deployment issues:
1. Check logs: `docker-compose logs`
2. Verify data: `./deploy/data-sync.sh --verify-only`  
3. Test health: `curl https://your-domain.com/api/health`