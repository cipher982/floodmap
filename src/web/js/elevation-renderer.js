/**
 * Client-side elevation data renderer for real-time flood visualization
 * Eliminates network bottleneck by computing flood colors in the browser
 */

function requireFloodmapApiUrl() {
    const helper = typeof window !== 'undefined' ? window.floodmapApiUrl : null;
    if (typeof helper !== 'function') {
        throw new Error('window.floodmapApiUrl is required before loading elevation tiles.');
    }
    return helper;
}

class ElevationRenderer {
    constructor() {
        // Elevation data cache (bounded LRU)
        this.elevationCache = new Map();
        this.elevationCacheMaxTiles = 512;

        // Rendered tile cache - temporary, cleared on water level change
        this.renderedCache = new Map();

        // Loading state tracking
        this.loadingTiles = new Map();
        this.terrainMetadataCache = new Map();

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
        this.ELEVATION_TILE_BYTE_LENGTH =
            this.TILE_SIZE * this.TILE_SIZE * Uint16Array.BYTES_PER_ELEMENT;
        this.ELEVATION_BATCH_MAGIC = 'FMB1';
        this.ELEVATION_BATCH_VERSION = 1;
        this.ELEVATION_MIN = -500;
        this.ELEVATION_MAX = 9000;
        this.ELEVATION_RANGE = this.ELEVATION_MAX - this.ELEVATION_MIN;

        // Precomputed ocean color for elevation mode (steel blue)
        this.OCEAN_RGBA = [70, 130, 180, 255];

        // In flood mode, treat NODATA as water (not "flooded land").
        this.WATER_RGBA = [70, 130, 180, 220];

        // HAND visualization mapping:
        // Color encodes height above local drainage within the selected slider
        // threshold. The threshold clips visibility; it does not create a flat
        // "inside" color. This keeps high thresholds readable as terrain.
        this.HAND_VIZ_ASINH_SCALE_M = 1.5;
        this.HAND_VIZ_STOPS = [
            { t: 0.0, color: [18, 97, 160, 220] },    // drainage floor
            { t: 0.18, color: [45, 165, 205, 205] },  // low terrace
            { t: 0.38, color: [98, 190, 170, 175] },  // valley floor
            { t: 0.65, color: [190, 204, 132, 125] }, // upper valley
            { t: 1.0, color: [205, 170, 110, 70] }    // selected edge
        ];
        this.HAND_NODATA_RGBA = [189, 0, 255, 107];

        // Elevation visualization mapping:
        // Use a stable global nonlinear mapping so lowlands retain contrast while
        // high mountains don't saturate to white.
        this.ELEV_VIZ_MAX_M = 6500; // covers Denali (~6190m) with headroom
        this.ELEV_VIZ_ASINH_SCALE_M = 120; // 80–150 is a good range for lowland contrast

        // Hypsometric tint stops (in meters, land only; ocean is handled separately).
        // These are interpolated smoothly after nonlinear compression.
        this.ELEV_VIZ_STOPS_M = [
            { m: 0, color: [34, 139, 34, 255] },     // green
            { m: 5, color: [76, 175, 80, 255] },     // brighter green
            { m: 15, color: [154, 205, 50, 255] },   // yellow-green
            { m: 30, color: [189, 214, 102, 255] },  // light yellow-green
            { m: 60, color: [210, 201, 128, 255] },  // tan
            { m: 100, color: [201, 186, 130, 255] }, // tan
            { m: 150, color: [184, 154, 108, 255] }, // light brown
            { m: 250, color: [160, 120, 80, 255] },  // brown
            { m: 400, color: [135, 105, 80, 255] },  // dark brown
            { m: 700, color: [120, 120, 120, 255] }, // gray
            { m: 1200, color: [150, 150, 150, 255] },// light gray
            { m: 2000, color: [185, 185, 185, 255] },// lighter gray
            { m: 3000, color: [225, 225, 225, 255] },// near-white
            { m: 4500, color: [245, 245, 245, 255] },// snow
            { m: 6500, color: [255, 255, 255, 255] } // peak snow
        ];
        this._elevVizStopTs = this.ELEV_VIZ_STOPS_M.map(s => ({
            t: this._elevVizTFromMeters(s.m),
            color: s.color
        }));
    }

    makeNoDataTile() {
        return new Uint16Array(this.TILE_SIZE * this.TILE_SIZE).fill(this.NODATA_VALUE);
    }

    _elevVizTFromMeters(elevationM) {
        const e = Math.max(0, Math.min(this.ELEV_VIZ_MAX_M, elevationM));
        const s = this.ELEV_VIZ_ASINH_SCALE_M;
        return Math.asinh(e / s) / Math.asinh(this.ELEV_VIZ_MAX_M / s);
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
        const url = this.buildElevationRequestUrl(`/v1/tiles/elevation-data/${z}/${x}/${y}.u16`);

        const loadPromise = fetch(url.toString(), { signal })
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
                    return this.makeNoDataTile();
                }

                // Debug: log tile loading (development mode only)
                if (window.DEBUG_TILES && Math.random() < 0.02) { // 2% of tiles when debugging enabled
                    console.log(`✅ Loaded tile data ${key}:`, {
                        size: elevationData.length,
                        first10: Array.from(elevationData.slice(0, 10)),
                        allSameValue: new Set(elevationData).size === 1
                    });
                }

                this.storeElevationTile(key, elevationData);
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
                console.error(`   URL was: ${url.toString()}`);
                this.loadingTiles.delete(key);
                // Return NODATA tile on error
                return this.makeNoDataTile();
            });

        this.loadingTiles.set(key, loadPromise);
        return loadPromise;
    }

    getTerrainLayerConfig(layer) {
        if (typeof window === 'undefined') return {};
        const routeContext = window.FLOODMAP_ROUTE_CONTEXT;
        const terrainLayers = routeContext && typeof routeContext === 'object'
            ? routeContext.terrainLayers
            : null;
        const config = terrainLayers && typeof terrainLayers === 'object'
            ? terrainLayers[layer]
            : null;
        return config && typeof config === 'object' ? config : {};
    }

    async getTerrainMetadata(layer, signal = null) {
        if (this.terrainMetadataCache.has(layer)) {
            return this.terrainMetadataCache.get(layer);
        }

        const url = new URL(
            requireFloodmapApiUrl()(`/v2/terrain/${layer}/metadata`),
            window.location.origin
        );
        const response = await fetch(url.toString(), { signal });
        if (!response.ok) {
            throw new Error(`Failed to load ${layer} terrain metadata: ${response.status}`);
        }
        const metadata = await response.json();
        this.terrainMetadataCache.set(layer, metadata);
        return metadata;
    }

    async buildTerrainTileRequestUrl(layer, z, x, y, signal = null) {
        const config = this.getTerrainLayerConfig(layer);
        let datasetVersion = typeof config.datasetVersion === 'string'
            ? config.datasetVersion
            : '';
        if (!datasetVersion) {
            const metadata = await this.getTerrainMetadata(layer, signal);
            datasetVersion = metadata.dataset_version;
        }
        if (!datasetVersion) {
            throw new Error(`No dataset version available for terrain layer ${layer}`);
        }

        const url = new URL(
            requireFloodmapApiUrl()(`/v2/terrain/${layer}/${datasetVersion}/${z}/${x}/${y}.u16`),
            window.location.origin
        );
        const tileVersion =
            (typeof window !== 'undefined'
                && (window.FLOODMAP_TILE_VERSION || window.FLOODMAP_ASSET_VERSION))
                ? (window.FLOODMAP_TILE_VERSION || window.FLOODMAP_ASSET_VERSION)
                : null;
        if (tileVersion) url.searchParams.set('v', tileVersion);
        return url;
    }

    async loadTerrainTile(layer, z, x, y, signal = null) {
        if (layer === 'elevation') {
            return this.loadElevationTile(z, x, y, signal);
        }

        const config = this.getTerrainLayerConfig(layer);
        if (config.enabled === false) {
            return this.makeNoDataTile();
        }

        const key = `${layer}:${z}/${x}/${y}`;
        if (this.elevationCache.has(key)) {
            this.stats.cacheHits++;
            const cached = this.elevationCache.get(key);
            this.elevationCache.delete(key);
            this.elevationCache.set(key, cached);
            return cached;
        }
        if (this.loadingTiles.has(key)) {
            return this.loadingTiles.get(key);
        }

        const loadPromise = this.buildTerrainTileRequestUrl(layer, z, x, y, signal)
            .then((url) => fetch(url.toString(), { signal }))
            .then((response) => {
                if (response.status === 404) {
                    return { buffer: null, cacheable: true };
                }
                if (response.status === 503) {
                    return { buffer: null, cacheable: false };
                }
                if (!response.ok) {
                    throw new Error(`Failed to load ${layer} terrain tile ${key}: ${response.status}`);
                }
                return response.arrayBuffer().then((buffer) => ({ buffer, cacheable: true }));
            })
            .then(({ buffer, cacheable }) => {
                const terrainData = buffer ? new Uint16Array(buffer) : this.makeNoDataTile();
                if (terrainData.length !== this.TILE_SIZE * this.TILE_SIZE) {
                    console.warn(`Invalid data size for ${layer} tile ${key}: ${terrainData.length} values`);
                    this.loadingTiles.delete(key);
                    return this.makeNoDataTile();
                }
                if (cacheable) {
                    this.storeElevationTile(key, terrainData);
                }
                this.loadingTiles.delete(key);
                this.stats.tilesLoaded++;
                return terrainData;
            })
            .catch((error) => {
                if (error?.name === 'AbortError') {
                    this.loadingTiles.delete(key);
                    throw error;
                }
                console.error(`Error loading ${layer} terrain tile ${key}:`, error);
                this.loadingTiles.delete(key);
                return this.makeNoDataTile();
            });

        this.loadingTiles.set(key, loadPromise);
        return loadPromise;
    }

    buildElevationRequestUrl(path) {
        const qs = new URLSearchParams();
        qs.set('method', 'precompressed');
        if (window.location.hostname === 'localhost') qs.set('t', String(Date.now()));
        const tileVersion =
            (typeof window !== 'undefined'
                && (window.FLOODMAP_TILE_VERSION || window.FLOODMAP_ASSET_VERSION))
                ? (window.FLOODMAP_TILE_VERSION || window.FLOODMAP_ASSET_VERSION)
                : null;
        if (tileVersion) qs.set('v', tileVersion);

        const url = new URL(requireFloodmapApiUrl()(path), window.location.origin);
        url.search = qs.toString();
        return url;
    }

    storeElevationTile(key, elevationData) {
        this.elevationCache.delete(key);
        this.elevationCache.set(key, elevationData);
        while (this.elevationCache.size > this.elevationCacheMaxTiles) {
            const oldestKey = this.elevationCache.keys().next().value;
            this.elevationCache.delete(oldestKey);
        }
    }

    parseElevationTileBatch(buffer) {
        const view = new DataView(buffer);
        if (view.byteLength < 7) {
            throw new Error('Elevation tile batch payload is too small');
        }

        const magic = String.fromCharCode(...new Uint8Array(buffer, 0, 4));
        if (magic !== this.ELEVATION_BATCH_MAGIC) {
            throw new Error(`Unexpected elevation batch magic: ${magic}`);
        }

        const version = view.getUint8(4);
        if (version !== this.ELEVATION_BATCH_VERSION) {
            throw new Error(`Unsupported elevation batch version: ${version}`);
        }

        const tileCount = view.getUint16(5, true);
        const headerLength = 7 + (tileCount * 5);
        const expectedLength = headerLength + (tileCount * this.ELEVATION_TILE_BYTE_LENGTH);
        if (view.byteLength !== expectedLength) {
            throw new Error(
                `Unexpected elevation batch size: ${view.byteLength} (expected ${expectedLength})`
            );
        }

        const entries = [];
        let metaOffset = 7;
        let dataOffset = headerLength;

        for (let index = 0; index < tileCount; index += 1) {
            const z = view.getUint8(metaOffset);
            const x = view.getUint16(metaOffset + 1, true);
            const y = view.getUint16(metaOffset + 3, true);
            const tileBuffer = buffer.slice(dataOffset, dataOffset + this.ELEVATION_TILE_BYTE_LENGTH);

            entries.push({
                z,
                x,
                y,
                elevationData: new Uint16Array(tileBuffer)
            });

            metaOffset += 5;
            dataOffset += this.ELEVATION_TILE_BYTE_LENGTH;
        }

        return entries;
    }

    async preloadTileBatch(tiles, signal = null) {
        const seenKeys = new Set();
        const uncachedTiles = [];

        for (const tile of Array.isArray(tiles) ? tiles : []) {
            if (!Number.isInteger(tile?.z) || !Number.isInteger(tile?.x) || !Number.isInteger(tile?.y)) {
                continue;
            }

            const key = `${tile.z}/${tile.x}/${tile.y}`;
            if (seenKeys.has(key) || this.elevationCache.has(key)) {
                continue;
            }

            seenKeys.add(key);
            uncachedTiles.push({ z: tile.z, x: tile.x, y: tile.y, key });
        }

        if (!uncachedTiles.length) {
            return [];
        }

        const url = this.buildElevationRequestUrl('/v1/tiles/elevation-batch.u16');
        const response = await fetch(url.toString(), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                tiles: uncachedTiles.map(({ z, x, y }) => ({ z, x, y }))
            }),
            signal
        });

        if (!response.ok) {
            throw new Error(`Failed to preload elevation batch: ${response.status}`);
        }

        const entries = this.parseElevationTileBatch(await response.arrayBuffer());
        if (entries.length !== uncachedTiles.length) {
            throw new Error(
                `Elevation batch entry mismatch: received ${entries.length}, expected ${uncachedTiles.length}`
            );
        }

        for (let index = 0; index < entries.length; index += 1) {
            const expected = uncachedTiles[index];
            const actual = entries[index];
            if (
                actual.z !== expected.z
                || actual.x !== expected.x
                || actual.y !== expected.y
            ) {
                throw new Error(
                    `Unexpected elevation batch tile order at index ${index}: `
                    + `received ${actual.z}/${actual.x}/${actual.y}, `
                    + `expected ${expected.z}/${expected.x}/${expected.y}`
                );
            }

            this.storeElevationTile(expected.key, actual.elevationData);
            this.stats.tilesLoaded++;
        }

        return entries.map((entry) => entry.elevationData);
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

    decodeHandHeight(uint16Value) {
        if (uint16Value === this.NODATA_VALUE) {
            return Number.NaN;
        }
        return uint16Value / 10.0;
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

        const t = this._elevVizTFromMeters(elevation);

        // Find enclosing stop interval (small table; linear scan is fine).
        const stops = this._elevVizStopTs;
        for (let i = 0; i < stops.length - 1; i++) {
            const a = stops[i];
            const b = stops[i + 1];
            if (t <= b.t) {
                const tt = (t - a.t) / Math.max(1e-12, (b.t - a.t));
                return this.interpolateColors(a.color, b.color, tt);
            }
        }
        return stops[stops.length - 1].color;
    }

    calculateHandColor(heightAboveDrainageM, thresholdM) {
        if (!Number.isFinite(heightAboveDrainageM)) {
            return this.colors.TRANSPARENT;
        }

        const threshold = Number.isFinite(thresholdM) ? Math.max(0, thresholdM) : 1.0;
        if (heightAboveDrainageM > threshold) {
            return this.colors.TRANSPARENT;
        }

        const visibleThreshold = Math.max(0.1, threshold);
        const scale = this.HAND_VIZ_ASINH_SCALE_M;
        const compressed = Math.asinh(Math.max(0, heightAboveDrainageM) / scale)
            / Math.asinh(visibleThreshold / scale);
        const t = Math.min(1, Math.max(0, compressed));
        for (let i = 0; i < this.HAND_VIZ_STOPS.length - 1; i++) {
            const a = this.HAND_VIZ_STOPS[i];
            const b = this.HAND_VIZ_STOPS[i + 1];
            if (t <= b.t) {
                const localT = (t - a.t) / Math.max(1e-12, b.t - a.t);
                return this.interpolateColors(a.color, b.color, localT);
            }
        }
        return this.HAND_VIZ_STOPS[this.HAND_VIZ_STOPS.length - 1].color;
    }

    calculateTileColor(rawValue, mode, waterLevel, showHandNoData = false) {
        if (mode === 'elevation') {
            return this.calculateElevationColor(this.decodeElevation(rawValue));
        }
        if (mode === 'hand') {
            if (rawValue === this.NODATA_VALUE && showHandNoData) {
                return this.HAND_NODATA_RGBA;
            }
            return this.calculateHandColor(this.decodeHandHeight(rawValue), waterLevel);
        }
        return this.calculateFloodColor(this.decodeElevation(rawValue), waterLevel);
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
