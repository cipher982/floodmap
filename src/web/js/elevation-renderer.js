/**
 * Client-side elevation data renderer for real-time flood visualization
 * Eliminates network bottleneck by computing flood colors in the browser
 */

class ElevationRenderer {
    constructor() {
        // Elevation data cache (bounded LRU)
        this.elevationCache = new Map();
        this.elevationCacheMaxTiles = 512;

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

        // Precomputed ocean color for elevation mode (steel blue)
        this.OCEAN_RGBA = [70, 130, 180, 255];

        // In flood mode, treat NODATA as water (not "flooded land").
        this.WATER_RGBA = [70, 130, 180, 220];
    }

    /**
     * Load elevation data for a tile
     * @param {number} z - Zoom level
     * @param {number} x - Tile X coordinate
     * @param {number} y - Tile Y coordinate
     * @param {AbortSignal|null} signal - Optional abort signal
     * @returns {Promise<Uint16Array>} Raw elevation data
     */
    async loadElevationTile(z, x, y, signal = null) {
        const key = `${z}/${x}/${y}`;

        // Check cache first
        if (this.elevationCache.has(key)) {
            this.stats.cacheHits++;
            const cached = this.elevationCache.get(key);
            // Refresh LRU position
            this.elevationCache.delete(key);
            this.elevationCache.set(key, cached);
            return cached;
        }

        // Check if already loading
        if (this.loadingTiles.has(key)) {
            return this.loadingTiles.get(key);
        }

        // Start loading
        // NOTE: We include a stable `v=` in production to avoid getting pinned to
        // cached precompressed-miss (NODATA) responses after data repairs.
        const qs = new URLSearchParams();
        qs.set('method', 'precompressed');
        if (window.location.hostname === 'localhost') qs.set('t', String(Date.now()));
        qs.set('v', '20251212g');
        const url = `/floodmap/api/v1/tiles/elevation-data/${z}/${x}/${y}.u16?${qs.toString()}`;

        const loadPromise = fetch(url, { signal })
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
                    console.warn(`⚠️ Invalid data size for tile ${key}: ${elevationData.length} bytes (expected ${this.TILE_SIZE * this.TILE_SIZE})`);
                    // Return NODATA tile for invalid data size
                    return new Uint16Array(this.TILE_SIZE * this.TILE_SIZE).fill(this.NODATA_VALUE);
                }

                // Debug: log tile loading (development mode only)
                if (window.DEBUG_TILES && Math.random() < 0.02) { // 2% of tiles when debugging enabled
                    console.log(`✅ Loaded tile data ${key}:`, {
                        size: elevationData.length,
                        first10: Array.from(elevationData.slice(0, 10)),
                        allSameValue: new Set(elevationData).size === 1
                    });
                }

                // Cache the data
                this.elevationCache.set(key, elevationData);
                while (this.elevationCache.size > this.elevationCacheMaxTiles) {
                    const oldestKey = this.elevationCache.keys().next().value;
                    this.elevationCache.delete(oldestKey);
                }
                this.loadingTiles.delete(key);
                this.stats.tilesLoaded++;

                return elevationData;
            })
            .catch(error => {
                if (error?.name === 'AbortError') {
                    // Abort is expected during rapid pan/zoom; do not log or cache.
                    this.loadingTiles.delete(key);
                    throw error;
                }
                console.error(`❌ Error loading elevation tile ${key}:`, error);
                console.error(`   URL was: ${url}`);
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
            // Use a consistent sentinel for downstream checks
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
            return this.WATER_RGBA;
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
     * Calculate elevation (topographical) color based on absolute elevation
     * @param {number} elevation - Elevation in meters
     * @returns {Array} RGBA color array
     */
    calculateElevationColor(elevation) {
        // Handle NODATA or below sea level consistently as ocean
        if (elevation === -32768 || Number.isNaN(elevation) || elevation < 0) {
            return this.OCEAN_RGBA; // Consistent ocean color
        }

        // Topographical color scheme based on elevation
        if (elevation < 50) {
            // Low coastal areas - green to yellow-green
            const t = elevation / 50;
            return this.interpolateColors([34, 139, 34, 255], [154, 205, 50, 255], t); // Forest green to yellow-green
        } else if (elevation < 200) {
            // Hills - yellow-green to brown
            const t = (elevation - 50) / 150;
            return this.interpolateColors([154, 205, 50, 255], [160, 82, 45, 255], t); // Yellow-green to saddle brown
        } else if (elevation < 500) {
            // Mountains - brown to gray
            const t = (elevation - 200) / 300;
            return this.interpolateColors([160, 82, 45, 255], [105, 105, 105, 255], t); // Saddle brown to dim gray
        } else if (elevation < 1000) {
            // High mountains - gray to light gray
            const t = (elevation - 500) / 500;
            return this.interpolateColors([105, 105, 105, 255], [169, 169, 169, 255], t); // Dim gray to dark gray
        } else {
            // Very high elevations - white
            return [255, 255, 255, 255]; // White
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
     * Clear rendered tile cache (call when water level changes)
     */
    clearRenderedCache() {
        this.renderedCache.clear();
        // Cache cleared
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
        // All caches cleared
    }

    /**
     * Configure max number of cached elevation tiles (LRU).
     * @param {number} maxTiles
     */
    setElevationCacheMaxTiles(maxTiles) {
        const n = Number(maxTiles);
        if (!Number.isFinite(n) || n <= 0) return;
        this.elevationCacheMaxTiles = Math.floor(n);
        while (this.elevationCache.size > this.elevationCacheMaxTiles) {
            const oldestKey = this.elevationCache.keys().next().value;
            this.elevationCache.delete(oldestKey);
        }
    }

    /**
     * Best-effort abort of an in-flight tile load (does not poison caches).
     * @param {number} z
     * @param {number} x
     * @param {number} y
     */
    abortElevationTileLoad(z, x, y) {
        const key = `${z}/${x}/${y}`;
        if (this.loadingTiles.has(key)) {
            // We don't own the AbortController here (MapLibre does); just drop dedupe entry.
            // This ensures new requests can proceed cleanly.
            this.loadingTiles.delete(key);
        }
    }

    /**
     * Quick scan to detect if a tile is entirely NODATA
     * @param {Uint16Array} elevationData
     * @returns {boolean}
     */
    isAllNoData(elevationData) {
        // Fast path: check a few sample points first
        const len = elevationData.length;
        const samples = [0, 1, 2, 3, 4, len >> 1, len - 1];
        if (!samples.every(i => elevationData[i] === this.NODATA_VALUE)) {
            return false;
        }
        // Full scan to confirm
        for (let i = 0; i < len; i++) {
            if (elevationData[i] !== this.NODATA_VALUE) return false;
        }
        return true;
    }

    /**
     * Fill an ImageData buffer with a solid RGBA color.
     * @param {ImageData} imageData
     * @param {Array} rgba
     */
    fillImageData(imageData, rgba) {
        const data = imageData.data;
        const [r, g, b, a] = rgba;
        for (let i = 0; i < data.length; i += 4) {
            data[i] = r;
            data[i + 1] = g;
            data[i + 2] = b;
            data[i + 3] = a;
        }
    }
}

// Export for use in map.js
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ElevationRenderer;
}
