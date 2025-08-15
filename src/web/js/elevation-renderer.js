/**
 * Client-side elevation data renderer for real-time flood visualization
 * Eliminates network bottleneck by computing flood colors in the browser
 */

class ElevationRenderer {
    constructor() {
        // Elevation data cache - permanent storage
        this.elevationCache = new Map();
        
        // Rendered tile cache - temporary, cleared on water level change
        this.renderedCache = new Map();
        
        // Loading state tracking
        this.loadingTiles = new Map();
        
        // Statistics
        this.stats = {
            tilesLoaded: 0,
            tilesRendered: 0,
            cacheHits: 0,
            renderTime: 0
        };
        
        // Color scheme matching server's color_mapping.py
        this.colors = {
            SAFE: [76, 175, 80, 120],      // Green, semi-transparent
            CAUTION: [255, 193, 7, 160],   // Yellow, more visible
            DANGER: [244, 67, 54, 200],    // Red, prominent
            FLOODED: [33, 150, 243, 220],  // Blue, very visible
            TRANSPARENT: [0, 0, 0, 0]      // Fully transparent
        };
        
        // Risk thresholds (meters relative to water level)
        this.thresholds = {
            SAFE: 5.0,       // 5m+ above water = safe
            CAUTION: 2.0,    // 2-5m above water = caution
            DANGER: 0.5      // 0.5-2m above water = danger
        };
        
        // Constants
        this.TILE_SIZE = 256;
        this.NODATA_VALUE = 65535;
        this.ELEVATION_MIN = -500;
        this.ELEVATION_MAX = 9000;
        this.ELEVATION_RANGE = this.ELEVATION_MAX - this.ELEVATION_MIN;
    }
    
    /**
     * Load elevation data for a tile
     * @param {number} z - Zoom level
     * @param {number} x - Tile X coordinate
     * @param {number} y - Tile Y coordinate
     * @returns {Promise<Uint16Array>} Raw elevation data
     */
    async loadElevationTile(z, x, y) {
        const key = `${z}/${x}/${y}`;
        
        // Check cache first
        if (this.elevationCache.has(key)) {
            this.stats.cacheHits++;
            return this.elevationCache.get(key);
        }
        
        // Check if already loading
        if (this.loadingTiles.has(key)) {
            return this.loadingTiles.get(key);
        }
        
        // Start loading
        const loadPromise = fetch(`/api/v1/tiles/elevation-data/${z}/${x}/${y}.u16`)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Failed to load elevation tile ${key}: ${response.status}`);
                }
                return response.arrayBuffer();
            })
            .then(buffer => {
                const elevationData = new Uint16Array(buffer);
                
                // Validate data size
                if (elevationData.length !== this.TILE_SIZE * this.TILE_SIZE) {
                    console.warn(`Invalid elevation data size for ${key}: ${elevationData.length}`);
                    // Return NODATA tile
                    return new Uint16Array(this.TILE_SIZE * this.TILE_SIZE).fill(this.NODATA_VALUE);
                }
                
                // Cache the data
                this.elevationCache.set(key, elevationData);
                this.loadingTiles.delete(key);
                this.stats.tilesLoaded++;
                
                return elevationData;
            })
            .catch(error => {
                console.error(`Error loading elevation tile ${key}:`, error);
                this.loadingTiles.delete(key);
                // Return NODATA tile on error
                return new Uint16Array(this.TILE_SIZE * this.TILE_SIZE).fill(this.NODATA_VALUE);
            });
        
        this.loadingTiles.set(key, loadPromise);
        return loadPromise;
    }
    
    /**
     * Decode elevation value from uint16
     * @param {number} uint16Value - Raw uint16 value
     * @returns {number} Elevation in meters
     */
    decodeElevation(uint16Value) {
        if (uint16Value === this.NODATA_VALUE) {
            return -32768; // NODATA sentinel value
        }
        // Decode from 0-65534 range to -500 to 9000m
        return (uint16Value / 65534) * this.ELEVATION_RANGE + this.ELEVATION_MIN;
    }
    
    /**
     * Calculate flood risk color based on elevation and water level
     * @param {number} elevation - Elevation in meters
     * @param {number} waterLevel - Water level in meters
     * @returns {Array} RGBA color array
     */
    calculateFloodColor(elevation, waterLevel) {
        // Handle NODATA (ocean/missing data)
        if (elevation === -32768) {
            return this.colors.FLOODED;
        }
        
        // Calculate relative elevation
        const relativeElevation = elevation - waterLevel;
        
        // Determine risk level and color
        if (relativeElevation >= this.thresholds.SAFE) {
            // Safe - transparent or very light green
            return this.colors.TRANSPARENT;
        } else if (relativeElevation >= this.thresholds.CAUTION) {
            // Interpolate between safe and caution
            const t = (this.thresholds.SAFE - relativeElevation) / 
                     (this.thresholds.SAFE - this.thresholds.CAUTION);
            return this.interpolateColors(this.colors.SAFE, this.colors.CAUTION, t);
        } else if (relativeElevation >= this.thresholds.DANGER) {
            // Interpolate between caution and danger
            const t = (this.thresholds.CAUTION - relativeElevation) / 
                     (this.thresholds.CAUTION - this.thresholds.DANGER);
            return this.interpolateColors(this.colors.CAUTION, this.colors.DANGER, t);
        } else if (relativeElevation >= -0.5) {
            // Interpolate between danger and flooded
            const t = (this.thresholds.DANGER - relativeElevation) / 
                     (this.thresholds.DANGER + 0.5);
            return this.interpolateColors(this.colors.DANGER, this.colors.FLOODED, t);
        } else {
            // Completely flooded
            return this.colors.FLOODED;
        }
    }
    
    /**
     * Interpolate between two colors
     * @param {Array} color1 - Start color [r, g, b, a]
     * @param {Array} color2 - End color [r, g, b, a]
     * @param {number} t - Interpolation factor (0-1)
     * @returns {Array} Interpolated color
     */
    interpolateColors(color1, color2, t) {
        return [
            Math.round(color1[0] * (1 - t) + color2[0] * t),
            Math.round(color1[1] * (1 - t) + color2[1] * t),
            Math.round(color1[2] * (1 - t) + color2[2] * t),
            Math.round(color1[3] * (1 - t) + color2[3] * t)
        ];
    }
    
    /**
     * Render flood overlay for a tile
     * @param {Uint16Array} elevationData - Raw elevation data
     * @param {number} waterLevel - Water level in meters
     * @param {string} tileKey - Tile identifier for caching
     * @returns {string} Data URL of rendered tile
     */
    renderFloodTile(elevationData, waterLevel, tileKey) {
        const startTime = performance.now();
        
        // Check rendered cache
        const cacheKey = `${tileKey}@${waterLevel}`;
        if (this.renderedCache.has(cacheKey)) {
            return this.renderedCache.get(cacheKey);
        }
        
        // Create off-screen canvas
        const canvas = document.createElement('canvas');
        canvas.width = this.TILE_SIZE;
        canvas.height = this.TILE_SIZE;
        const ctx = canvas.getContext('2d', { alpha: true });
        
        // Create image data
        const imageData = ctx.createImageData(this.TILE_SIZE, this.TILE_SIZE);
        const data = imageData.data;
        
        // Process each pixel
        for (let i = 0; i < elevationData.length; i++) {
            // Decode elevation
            const elevation = this.decodeElevation(elevationData[i]);
            
            // Calculate flood color
            const color = this.calculateFloodColor(elevation, waterLevel);
            
            // Set pixel color
            const offset = i * 4;
            data[offset] = color[0];     // Red
            data[offset + 1] = color[1]; // Green
            data[offset + 2] = color[2]; // Blue
            data[offset + 3] = color[3]; // Alpha
        }
        
        // Put image data to canvas
        ctx.putImageData(imageData, 0, 0);
        
        // Convert to data URL
        const dataUrl = canvas.toDataURL('image/png');
        
        // Cache the rendered tile
        this.renderedCache.set(cacheKey, dataUrl);
        
        // Update stats
        const renderTime = performance.now() - startTime;
        this.stats.renderTime = renderTime;
        this.stats.tilesRendered++;
        
        console.debug(`Rendered tile ${tileKey} in ${renderTime.toFixed(1)}ms`);
        
        return dataUrl;
    }
    
    /**
     * Clear rendered tile cache (call when water level changes)
     */
    clearRenderedCache() {
        this.renderedCache.clear();
        console.debug('Cleared rendered tile cache');
    }
    
    /**
     * Get statistics
     * @returns {Object} Current statistics
     */
    getStats() {
        return {
            ...this.stats,
            elevationCacheSize: this.elevationCache.size,
            renderedCacheSize: this.renderedCache.size,
            loadingCount: this.loadingTiles.size
        };
    }
    
    /**
     * Preload elevation tiles for an area
     * @param {Array} tiles - Array of {z, x, y} objects
     * @returns {Promise} Resolves when all tiles are loaded
     */
    async preloadTiles(tiles) {
        const promises = tiles.map(({z, x, y}) => this.loadElevationTile(z, x, y));
        return Promise.all(promises);
    }
    
    /**
     * Clear all caches
     */
    clearAllCaches() {
        this.elevationCache.clear();
        this.renderedCache.clear();
        this.loadingTiles.clear();
        console.debug('Cleared all caches');
    }
}

// Export for use in map.js
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ElevationRenderer;
}