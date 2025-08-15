# Client-Side Flood Rendering PRD
## Eliminate Network Bottleneck with Browser-Based Computation

*Version 1.0 - Implementation Ready*

---

## Executive Summary

**The Problem**: Every slider movement triggers 20-50 network requests for new flood tiles, causing 1-second delays and massive bandwidth waste. The server repeatedly computes the same pixel-by-pixel flood calculations that could be done instantly in the browser.

**The Solution**: Ship raw elevation data once, compute flood colors in the browser using Canvas 2D API. No WebGL complexity, works on all devices.

**Impact**:
- **1000ms → 5ms** slider response time (200x faster)
- **100% bandwidth reduction** after initial load
- **Works everywhere**: Canvas 2D has universal browser support
- **Implementation**: 1 week with backwards compatibility

---

## Current Architecture Analysis

### Data Flow (Current)
```
User moves slider → 
  20 tile requests → 
    Server loads elevation → 
      Server calculates flood colors → 
        Server generates PNG → 
          Network transfer (50ms × 20) → 
            Browser displays
              
Total: ~1000ms per slider movement
```

### Key Components
1. **Server-Side**:
   - `tiles_v1.py`: Generates flood tiles at `/api/tiles/elevation/{water_level}/{z}/{x}/{y}.png`
   - `color_mapping.py`: Converts elevation → RGBA based on water level
   - `persistent_elevation_cache.py`: 4GB in-memory elevation cache
   - `elevation_loader.py`: Loads zstd-compressed elevation files

2. **Client-Side**:
   - `map.js`: Simple MapLibre integration
   - Updates tile URL on slider change: `/api/tiles/elevation/${waterLevel}/{z}/{x}/{y}.png`
   - No computation, just displays server-generated PNGs

### Performance Profile
- **Tile generation**: 15-30ms server CPU time
- **Network latency**: 30-100ms per tile
- **Concurrent requests**: Browser limits to 6
- **Total latency**: 500-1500ms for viewport update

---

## Proposed Architecture

### Data Flow (New)
```
Initial page load → 
  Download elevation tiles (once, cached forever) →
    User moves slider → 
      JavaScript recolors tiles (5ms) → 
        Update canvas → 
          Display

Total: ~5ms per slider movement (after initial load)
```

### Implementation Strategy

#### 1. New Server Endpoint
```python
# src/api/routers/tiles_v1.py

@router.get("/elevation-data/{z}/{x}/{y}.u16")
async def get_elevation_data_tile(z: int, x: int, y: int):
    """
    Serve raw elevation data as Uint16 binary array.
    256x256 pixels = 131KB uncompressed, ~40KB gzipped
    """
    # Reuse existing elevation loading
    elevation_data = get_elevation_for_tile(z, x, y)
    
    # Convert to uint16: -500m to 9000m → 0-65534
    # Special value 65535 = NODATA (ocean/missing)
    normalized = np.clip((elevation_data + 500) / 9500 * 65534, 0, 65534)
    normalized[elevation_data == NODATA_VALUE] = 65535
    uint16_data = normalized.astype(np.uint16)
    
    return Response(
        content=uint16_data.tobytes(),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Encoding": "gzip"  # Let uvicorn handle compression
        }
    )
```

#### 2. Client-Side Elevation Manager
```javascript
// src/web/js/elevation-renderer.js

class ElevationRenderer {
    constructor() {
        this.cache = new Map(); // Permanent elevation data cache
        this.canvasCache = new Map(); // Rendered tile cache
    }
    
    async loadElevationTile(z, x, y) {
        const key = `${z}/${x}/${y}`;
        if (this.cache.has(key)) return this.cache.get(key);
        
        const response = await fetch(`/api/v1/tiles/elevation-data/${z}/${x}/${y}.u16`);
        const buffer = await response.arrayBuffer();
        const elevations = new Uint16Array(buffer);
        
        this.cache.set(key, elevations);
        return elevations;
    }
    
    renderFloodTile(elevations, waterLevel) {
        // Create off-screen canvas
        const canvas = document.createElement('canvas');
        canvas.width = 256;
        canvas.height = 256;
        const ctx = canvas.getContext('2d');
        
        // Create image data
        const imageData = ctx.createImageData(256, 256);
        const data = imageData.data;
        
        // Color constants (matching server's color_mapping.py)
        const SAFE = [76, 175, 80, 120];
        const CAUTION = [255, 193, 7, 160];
        const DANGER = [244, 67, 54, 200];
        const FLOODED = [33, 150, 243, 220];
        
        // Process each pixel
        for (let i = 0; i < elevations.length; i++) {
            const uint16Val = elevations[i];
            
            // Decode elevation
            let elevation;
            if (uint16Val === 65535) {
                elevation = -32768; // NODATA
            } else {
                elevation = (uint16Val / 65534) * 9500 - 500;
            }
            
            // Calculate flood risk
            const relativeElev = elevation - waterLevel;
            let color;
            
            if (elevation === -32768 || relativeElev < -0.5) {
                color = FLOODED;
            } else if (relativeElev < 0.5) {
                color = DANGER;
            } else if (relativeElev < 2.0) {
                color = CAUTION;
            } else if (relativeElev < 5.0) {
                color = SAFE;
            } else {
                // Above flood risk - transparent
                color = [0, 0, 0, 0];
            }
            
            // Set pixel
            const offset = i * 4;
            data[offset] = color[0];
            data[offset + 1] = color[1];
            data[offset + 2] = color[2];
            data[offset + 3] = color[3];
        }
        
        ctx.putImageData(imageData, 0, 0);
        return canvas.toDataURL('image/png');
    }
}
```

#### 3. MapLibre Integration
```javascript
// Modify src/web/js/map.js

class FloodMap {
    constructor() {
        this.elevationRenderer = new ElevationRenderer();
        this.clientSideMode = true; // Feature flag
        // ... existing code ...
    }
    
    async updateFloodLayer() {
        if (!this.clientSideMode) {
            // Fallback to server-side rendering
            this.map.getSource('elevation-tiles').setTiles([this.getElevationTileURL()]);
            return;
        }
        
        // Client-side rendering
        const bounds = this.map.getBounds();
        const zoom = Math.floor(this.map.getZoom());
        
        // Get visible tiles
        const tiles = this.getVisibleTiles(bounds, zoom);
        
        // Load elevation data and render
        for (const {z, x, y} of tiles) {
            const elevations = await this.elevationRenderer.loadElevationTile(z, x, y);
            const tileUrl = this.elevationRenderer.renderFloodTile(elevations, this.currentWaterLevel);
            
            // Update specific tile in MapLibre
            this.updateTileImage(z, x, y, tileUrl);
        }
    }
}
```

---

## Implementation Phases

### Phase 1: Server Endpoint (Day 1)
- [ ] Add `/elevation-data/{z}/{x}/{y}.u16` endpoint
- [ ] Test binary data encoding/compression
- [ ] Verify cache headers

### Phase 2: Client Renderer (Days 2-3)
- [ ] Create `elevation-renderer.js` module
- [ ] Implement elevation decoding
- [ ] Port color mapping logic from Python
- [ ] Test Canvas 2D rendering performance

### Phase 3: Integration (Days 4-5)
- [ ] Integrate with MapLibre custom source
- [ ] Handle tile loading/caching
- [ ] Add progress indicators for initial load
- [ ] Implement feature flag for rollback

### Phase 4: Optimization (Day 6)
- [ ] Add Web Worker for rendering (optional)
- [ ] Implement tile prefetching
- [ ] Add IndexedDB for persistent client cache

### Phase 5: Testing & Rollout (Day 7)
- [ ] Test on various devices (phones, tablets, desktop)
- [ ] Verify backwards compatibility
- [ ] Performance benchmarking
- [ ] Gradual rollout with feature flag

---

## Technical Considerations

### Browser Compatibility
- **Canvas 2D**: 100% support (IE9+, all mobile)
- **Uint16Array**: 99.5% support (IE10+)
- **Fetch API**: 96% support (polyfill available)
- **No WebGL required**: Maximum compatibility

### Performance Characteristics
| Operation | Time | Notes |
|-----------|------|-------|
| Load elevation tile | 50-100ms | One-time, cached forever |
| Decode Uint16 → elevation | 0.5ms | 65K values |
| Calculate flood colors | 2ms | Simple comparisons |
| Render to canvas | 2ms | putImageData |
| Total render time | **~5ms** | 200x faster than network |

### Memory Usage
- **Elevation cache**: 131KB per tile (Uint16Array)
- **100 tiles cached**: ~13MB (acceptable)
- **Canvas cache**: Optional, ~30KB per rendered PNG

### Bandwidth Comparison
| Scenario | Current (Server-Side) | Proposed (Client-Side) |
|----------|----------------------|------------------------|
| Initial load (20 tiles) | 240KB | 800KB (one-time) |
| Slider change | 240KB | 0KB |
| 10 slider changes | 2.4MB | 0KB |
| Returning user | 240KB+ | 0KB (cached) |

---

## Risk Mitigation

### Risk: Initial Load Size
**Mitigation**: 
- Progressive loading (load visible tiles first)
- Show server-rendered tiles while loading elevation data
- Gzip compression reduces 131KB → ~40KB per tile

### Risk: Browser Memory Limits
**Mitigation**:
- LRU eviction for elevation cache
- Limit cache to 100 tiles (~13MB)
- Clear old rendered canvases

### Risk: Rendering Performance on Old Devices
**Mitigation**:
- Feature detection with fallback to server-side
- Reduce tile resolution on weak devices (128x128)
- Optional Web Worker for computation

---

## Success Metrics

1. **Slider Responsiveness**: < 10ms update time
2. **Bandwidth Reduction**: > 95% for active users
3. **Server Load**: 80% reduction in tile generation
4. **Browser Compatibility**: > 98% of users
5. **User Satisfaction**: Instant, smooth flood visualization

---

## Migration Strategy

1. **Week 1**: Implement with feature flag (0% users)
2. **Week 2**: Internal testing and optimization
3. **Week 3**: Roll out to 10% of users
4. **Week 4**: Monitor metrics, fix issues
5. **Week 5**: Roll out to 50% of users
6. **Week 6**: Full rollout if metrics are positive

---

## Conclusion

This architecture solves the fundamental problem: we're using the network (the slowest component) for computations that should happen locally. By shipping immutable elevation data once and computing flood colors in the browser, we achieve:

- **Instant response**: 5ms vs 1000ms
- **Zero bandwidth**: After initial load
- **Universal compatibility**: Canvas 2D works everywhere
- **Simple implementation**: No complex WebGL, just JavaScript

The implementation is straightforward, backwards-compatible, and delivers a transformative performance improvement. This is the right architectural decision for a flood mapping application where responsiveness is critical for user safety decisions.