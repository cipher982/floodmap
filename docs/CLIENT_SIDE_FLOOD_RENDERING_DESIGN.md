# Client-Side Flood Rendering Architecture
## From Server-Side Tiles to GPU-Accelerated Real-Time Rendering

### Executive Summary

**Current Architecture Problems**:
- Every slider movement triggers 20-50 tile requests over network (50ms latency × 20 = 1000ms)
- Server CPU wastes cycles computing per-pixel flood calculations
- Bandwidth abuse: Sending full PNG tiles when only colors change
- Cache invalidation on every water level change

**Carmack Solution**: Ship elevation data once, render flood colors on GPU
- **Performance**: 0.16ms GPU computation vs 1000ms network round-trip
- **Bandwidth**: One-time 65KB elevation download vs continuous 12KB PNGs
- **UX**: 60fps smooth slider interaction vs jerky network-dependent updates

---

## Technical Architecture

### 1. Data Format Transformation

**Current**: Server generates colored PNG tiles per water level
```
/api/tiles/elevation/{water_level}/{z}/{x}/{y}.png → 12KB colored PNG
```

**Proposed**: Server sends raw elevation data tiles
```
/api/tiles/elevation-data/{z}/{x}/{y}.bin → 65KB uint16 elevation array
```

**Elevation Data Format**:
```javascript
// 256x256 pixels, 16-bit elevation values
// Format: Uint16Array (2 bytes per pixel)
// Range: 0-65535 representing -500m to +9000m
// Special value: 65535 = NODATA (ocean/missing data)
```

### 2. MapLibre WebGL Custom Layer Implementation

```javascript
class FloodRenderLayer {
    constructor() {
        this.id = 'flood-render';
        this.type = 'custom';
        this.renderingMode = '2d';
    }

    onAdd(map, gl) {
        // Compile shaders
        this.program = this.createShaderProgram(gl);

        // Create texture for elevation data
        this.elevationTexture = gl.createTexture();

        // Set up vertex buffer (full-screen quad)
        this.vertexBuffer = this.createQuadBuffer(gl);
    }

    render(gl, matrix) {
        gl.useProgram(this.program);

        // Bind elevation texture
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, this.elevationTexture);

        // Set uniforms
        gl.uniform1f(this.waterLevelUniform, this.currentWaterLevel);
        gl.uniformMatrix4fv(this.matrixUniform, false, matrix);

        // Draw
        gl.drawArrays(gl.TRIANGLES, 0, 6);
    }
}
```

### 3. Fragment Shader for Flood Coloring

```glsl
precision highp float;

uniform sampler2D u_elevation;
uniform float u_waterLevel;

varying vec2 v_texCoord;

// Color constants matching server-side color_mapping.py
const vec4 SAFE_COLOR = vec4(0.298, 0.686, 0.314, 0.47);      // Green
const vec4 CAUTION_COLOR = vec4(1.0, 0.757, 0.027, 0.627);    // Yellow
const vec4 DANGER_COLOR = vec4(0.957, 0.263, 0.212, 0.784);   // Red
const vec4 FLOODED_COLOR = vec4(0.129, 0.588, 0.953, 0.863);  // Blue

void main() {
    // Sample elevation from texture (16-bit value normalized to 0-1)
    float normalizedElevation = texture2D(u_elevation, v_texCoord).r;

    // Convert to actual elevation in meters
    float elevation = normalizedElevation * 9500.0 - 500.0;

    // Check for NODATA (ocean)
    if (normalizedElevation >= 0.9999) {
        gl_FragColor = FLOODED_COLOR;
        return;
    }

    // Calculate relative elevation
    float relativeElevation = elevation - u_waterLevel;

    // Determine flood risk color
    vec4 color;
    if (relativeElevation >= 5.0) {
        color = SAFE_COLOR;
    } else if (relativeElevation >= 2.0) {
        // Interpolate between safe and caution
        float t = (5.0 - relativeElevation) / 3.0;
        color = mix(SAFE_COLOR, CAUTION_COLOR, t);
    } else if (relativeElevation >= 0.5) {
        // Interpolate between caution and danger
        float t = (2.0 - relativeElevation) / 1.5;
        color = mix(CAUTION_COLOR, DANGER_COLOR, t);
    } else if (relativeElevation >= -0.5) {
        // Interpolate between danger and flooded
        float t = (0.5 - relativeElevation) / 1.0;
        color = mix(DANGER_COLOR, FLOODED_COLOR, t);
    } else {
        color = FLOODED_COLOR;
    }

    gl_FragColor = color;
}
```

### 4. Elevation Data Loading Strategy

```javascript
class ElevationDataManager {
    constructor() {
        this.cache = new Map(); // Permanent cache
        this.loadingTiles = new Map(); // Prevent duplicate requests
    }

    async loadElevationTile(z, x, y) {
        const key = `${z}/${x}/${y}`;

        // Check cache
        if (this.cache.has(key)) {
            return this.cache.get(key);
        }

        // Check if already loading
        if (this.loadingTiles.has(key)) {
            return this.loadingTiles.get(key);
        }

        // Load elevation data
        const loadPromise = fetch(`/api/tiles/elevation-data/${z}/${x}/${y}.bin`)
            .then(response => response.arrayBuffer())
            .then(buffer => {
                const elevationData = new Uint16Array(buffer);
                this.cache.set(key, elevationData);
                this.loadingTiles.delete(key);
                return elevationData;
            });

        this.loadingTiles.set(key, loadPromise);
        return loadPromise;
    }
}
```

### 5. Server-Side Elevation Data Endpoint

```python
@router.get("/elevation-data/{z}/{x}/{y}.bin")
async def get_elevation_data_tile(
    z: int = Path(...),
    x: int = Path(...),
    y: int = Path(...)
):
    """Serve raw elevation data as binary uint16 array."""

    # Get elevation data (reuse existing elevation_loader)
    elevation_data = get_elevation_for_tile(z, x, y)  # Returns numpy array

    # Convert to uint16 (0-65535 range)
    # Map -500m to +9000m → 0 to 65534, with 65535 as NODATA
    normalized = np.clip((elevation_data + 500) / 9500 * 65534, 0, 65534)
    normalized[elevation_data == NODATA_VALUE] = 65535
    elevation_uint16 = normalized.astype(np.uint16)

    # Return as binary data
    return Response(
        content=elevation_uint16.tobytes(),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Type": "application/octet-stream"
        }
    )
```

---

## Implementation Plan

### Phase 1: Server-Side Data Endpoint (2 hours)
1. Add `/elevation-data/{z}/{x}/{y}.bin` endpoint
2. Implement uint16 elevation encoding
3. Test with curl to verify binary output

### Phase 2: Client-Side WebGL Layer (4 hours)
1. Create FloodRenderLayer class
2. Implement shader compilation
3. Add elevation texture loading
4. Test with hardcoded water level

### Phase 3: Integration (2 hours)
1. Wire up slider to shader uniform
2. Handle tile loading/unloading
3. Add fallback for WebGL unavailable

### Phase 4: Optimization (2 hours)
1. Implement tile prefetching
2. Add compressed elevation format (zstd)
3. Profile and optimize shader performance

---

## Performance Comparison

| Metric | Current (Server-Side) | Proposed (Client-Side) | Improvement |
|--------|----------------------|------------------------|-------------|
| Slider Response Time | 1000ms | 0.16ms | **6,250x faster** |
| Bandwidth per Pan | 240KB (20 tiles) | 0KB (cached) | **100% reduction** |
| Initial Load | 240KB | 780KB (one-time) | -3.25x (but cached forever) |
| Server CPU Load | High (image generation) | None | **100% reduction** |
| Smoothness | Jerky (network dependent) | 60fps | **Butter smooth** |

---

## Risks and Mitigations

### Risk: WebGL Support
- **Mitigation**: Fallback to current server-side rendering for ~2% of users without WebGL

### Risk: Initial Load Size
- **Mitigation**: Progressive loading, show low-res first, compress with zstd

### Risk: Mobile GPU Performance
- **Mitigation**: Adaptive quality, reduce tile resolution on weak devices

---

## Success Metrics

1. **Slider latency**: < 16ms (60fps)
2. **Bandwidth reduction**: > 90% for active users
3. **Server CPU reduction**: > 80%
4. **User satisfaction**: Smooth, instant flood visualization

---

## Conclusion

This architecture fundamentally fixes the performance bottleneck by moving computation to where it belongs - the client's GPU. It's a classic Carmack-style optimization: identify the real problem (network latency), eliminate it entirely (client-side rendering), and leverage massively parallel hardware (GPU) for what it does best (per-pixel calculations).

The result: instant, smooth, bandwidth-efficient flood visualization that scales to millions of users.
