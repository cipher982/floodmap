/**
 * WebWorker for client-side tile rendering
 * Moves CPU-intensive pixel processing off the main thread
 */

// Import or inline the ElevationRenderer logic
// Since workers can't import ES6 modules directly, we inline the necessary parts

class WorkerElevationRenderer {
    constructor() {
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
        this.NODATA_VALUE = 65535;
        this.ELEVATION_MIN = -500;
        this.ELEVATION_MAX = 9000;
        this.ELEVATION_RANGE = this.ELEVATION_MAX - this.ELEVATION_MIN;

        // Precomputed ocean color for elevation mode (steel blue)
        this.OCEAN_RGBA = [70, 130, 180, 255];

        // LUT state
        this._elevationLut = null;
        this._floodLut = null;
        this._floodLutWlKey = null;
        this._lutRebuilds = 0;
    }

    /**
     * Decode elevation value from uint16
     */
    decodeElevation(uint16Value) {
        if (uint16Value === this.NODATA_VALUE) {
            return -32768; // NODATA sentinel value
        }
        return (uint16Value / 65534) * this.ELEVATION_RANGE + this.ELEVATION_MIN;
    }

    /**
     * Calculate flood risk color based on elevation and water level
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
            return this.colors.TRANSPARENT;
        } else if (relativeElevation >= this.thresholds.CAUTION) {
            const t = (this.thresholds.SAFE - relativeElevation) /
                     (this.thresholds.SAFE - this.thresholds.CAUTION);
            return this.interpolateColors(this.colors.SAFE, this.colors.CAUTION, t);
        } else if (relativeElevation >= this.thresholds.DANGER) {
            const t = (this.thresholds.CAUTION - relativeElevation) /
                     (this.thresholds.CAUTION - this.thresholds.DANGER);
            return this.interpolateColors(this.colors.CAUTION, this.colors.DANGER, t);
        } else if (relativeElevation >= -0.5) {
            const t = (this.thresholds.DANGER - relativeElevation) /
                     (this.thresholds.DANGER + 0.5);
            return this.interpolateColors(this.colors.DANGER, this.colors.FLOODED, t);
        } else {
            return this.colors.FLOODED;
        }
    }

    /**
     * Calculate elevation (topographical) color based on absolute elevation
     */
    calculateElevationColor(elevation) {
        // Handle NODATA or below sea level consistently as ocean
        if (elevation === -32768 || Number.isNaN(elevation) || elevation < 0) {
            return this.OCEAN_RGBA;
        }

        // Topographical color scheme based on elevation
        if (elevation < 50) {
            const t = elevation / 50;
            return this.interpolateColors([34, 139, 34, 255], [154, 205, 50, 255], t);
        } else if (elevation < 200) {
            const t = (elevation - 50) / 150;
            return this.interpolateColors([154, 205, 50, 255], [160, 82, 45, 255], t);
        } else if (elevation < 500) {
            const t = (elevation - 200) / 300;
            return this.interpolateColors([160, 82, 45, 255], [105, 105, 105, 255], t);
        } else if (elevation < 1000) {
            const t = (elevation - 500) / 500;
            return this.interpolateColors([105, 105, 105, 255], [169, 169, 169, 255], t);
        } else {
            return [255, 255, 255, 255];
        }
    }

    /**
     * Interpolate between two colors
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
     * Check if tile is entirely NODATA
     */
    isAllNoData(elevationData) {
        const len = elevationData.length;
        const samples = [0, 1, 2, 3, 4, len >> 1, len - 1];
        if (!samples.every(i => elevationData[i] === this.NODATA_VALUE)) {
            return false;
        }
        for (let i = 0; i < len; i++) {
            if (elevationData[i] !== this.NODATA_VALUE) return false;
        }
        return true;
    }

    /**
     * Fill a pixel buffer with solid RGBA
     */
    fillPixelBuffer(pixelData, rgba) {
        const [r, g, b, a] = rgba;
        for (let i = 0; i < pixelData.length; i += 4) {
            pixelData[i] = r;
            pixelData[i + 1] = g;
            pixelData[i + 2] = b;
            pixelData[i + 3] = a;
        }
    }

    _packRgbaToU32(r, g, b, a) {
        // Little-endian pack for Uint32Array view on Uint8ClampedArray buffer:
        // bytes [r,g,b,a] => u32 = a<<24 | b<<16 | g<<8 | r
        return ((a & 255) << 24) | ((b & 255) << 16) | ((g & 255) << 8) | (r & 255);
    }

    buildElevationLut() {
        const lut = new Uint32Array(65536);
        for (let u = 0; u < 65536; u++) {
            const elevation = this.decodeElevation(u);
            const [r, g, b, a] = this.calculateElevationColor(elevation);
            lut[u] = this._packRgbaToU32(r, g, b, a);
        }
        this._lutRebuilds++;
        return lut;
    }

    buildFloodLut(waterLevel) {
        const lut = new Uint32Array(65536);
        for (let u = 0; u < 65536; u++) {
            const elevation = this.decodeElevation(u);
            const [r, g, b, a] = this.calculateFloodColor(elevation, waterLevel);
            lut[u] = this._packRgbaToU32(r, g, b, a);
        }
        this._lutRebuilds++;
        return lut;
    }

    getElevationLut() {
        if (!this._elevationLut) this._elevationLut = this.buildElevationLut();
        return this._elevationLut;
    }

    getFloodLut(waterLevel) {
        const wlKey = Math.round(waterLevel * 10) / 10; // 0.1m steps to match wl=
        if (!this._floodLut || this._floodLutWlKey !== wlKey) {
            this._floodLut = this.buildFloodLut(wlKey);
            this._floodLutWlKey = wlKey;
        }
        return this._floodLut;
    }
}

// Worker instance
const renderer = new WorkerElevationRenderer();

function supportsOffscreenPng() {
    return typeof OffscreenCanvas !== 'undefined' &&
        typeof OffscreenCanvas.prototype.getContext === 'function';
}

async function encodePngOffscreen(pixelBuffer, width, height) {
    const canvas = new OffscreenCanvas(width, height);
    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) throw new Error('OffscreenCanvas 2D context unavailable');
    const imageData = new ImageData(new Uint8ClampedArray(pixelBuffer), width, height);
    ctx.putImageData(imageData, 0, 0);
    const blob = await canvas.convertToBlob({ type: 'image/png' });
    return await blob.arrayBuffer();
}

// Message handler
self.onmessage = function(e) {
    const { type, jobId, data } = e.data;

    if (type === 'set-debug') {
        self.DEBUG_TILES = !!data?.debug;
        return;
    }

    if (type === 'cancel') {
        // Best-effort cancellation: mark job as cancelled. Rendering loop checks periodically.
        self._cancelledJobIds = self._cancelledJobIds || new Set();
        self._cancelledJobIds.add(jobId);
        return;
    }

    if (type === 'render') {
        try {
            const { elevationData, mode, waterLevel, width, height } = data;

            // Fast check before doing any work
            if (self._cancelledJobIds?.has(jobId)) {
                self._cancelledJobIds.delete(jobId);
                return;
            }

            // Convert back to Uint16Array
            const elevationArray = new Uint16Array(elevationData);

            // Allocate pixel buffer (avoid ImageData dependency in worker context)
            const pixelData = new Uint8ClampedArray(width * height * 4);
            const pixelU32 = new Uint32Array(pixelData.buffer);

            // Fast-path: check if entire tile is NODATA
            if (renderer.isAllNoData(elevationArray)) {
                const fillColor = (mode === 'flood')
                    ? renderer.colors.FLOODED
                    : renderer.OCEAN_RGBA;

                const packed = renderer._packRgbaToU32(fillColor[0], fillColor[1], fillColor[2], fillColor[3]);
                pixelU32.fill(packed);

                // Send back the pixel buffer
                if (supportsOffscreenPng()) {
                    encodePngOffscreen(pixelData.buffer, width, height)
                        .then(pngBuffer => {
                            self.postMessage({ type: 'complete', jobId, pngBuffer }, [pngBuffer]);
                        })
                        .catch(() => {
                            self.postMessage({ type: 'complete', jobId, imageData: pixelData.buffer }, [pixelData.buffer]);
                        });
                    return;
                }
                self.postMessage({ type: 'complete', jobId, imageData: pixelData.buffer }, [pixelData.buffer]);
                return;
            }

            const lut = (mode === 'elevation')
                ? renderer.getElevationLut()
                : renderer.getFloodLut(waterLevel);

            // Process each pixel: rgba32 = lut[u16]
            for (let i = 0; i < elevationArray.length; i++) {
                // Check cancellation periodically without adding too much overhead
                if ((i & 1023) === 0 && self._cancelledJobIds?.has(jobId)) {
                    self._cancelledJobIds.delete(jobId);
                    return;
                }
                pixelU32[i] = lut[elevationArray[i]];
            }

            if (self._cancelledJobIds?.has(jobId)) {
                self._cancelledJobIds.delete(jobId);
                return;
            }

            if (supportsOffscreenPng()) {
                encodePngOffscreen(pixelData.buffer, width, height)
                    .then(pngBuffer => {
                        if (self._cancelledJobIds?.has(jobId)) {
                            self._cancelledJobIds.delete(jobId);
                            return;
                        }
                        self.postMessage({ type: 'complete', jobId, pngBuffer }, [pngBuffer]);
                    })
                    .catch(() => {
                        self.postMessage({ type: 'complete', jobId, imageData: pixelData.buffer }, [pixelData.buffer]);
                    });
                return;
            }

            // Send back the pixel buffer (transfer ownership for performance)
            self.postMessage({ type: 'complete', jobId, imageData: pixelData.buffer }, [pixelData.buffer]);

            // Occasionally report LUT rebuild count (debug only)
            if (self.DEBUG_TILES) {
                self.postMessage({ type: 'stats', lutRebuilds: renderer._lutRebuilds });
            }

        } catch (error) {
            self.postMessage({
                type: 'error',
                jobId,
                error: error.message
            });
        }
    }
};

// Signal that worker is ready (or unsupported if core APIs are missing)
if (typeof Uint8ClampedArray === 'undefined' || typeof Uint16Array === 'undefined') {
    self.postMessage({ type: 'unsupported', error: 'Typed arrays not available' });
} else {
    self.postMessage({ type: 'ready' });
}
