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
        // In flood mode, treat NODATA as water (not "flooded land").
        this.WATER_RGBA = [70, 130, 180, 220];

        // Elevation visualization mapping:
        // Use a stable global nonlinear mapping so lowlands retain contrast while
        // high mountains don't saturate to white.
        this.ELEV_VIZ_MAX_M = 6500;
        this.ELEV_VIZ_ASINH_SCALE_M = 120;

        // Hypsometric tint stops (in meters). Ocean is handled separately.
        this.ELEV_VIZ_STOPS_M = [
            { m: 0, color: [34, 139, 34, 255] },
            { m: 5, color: [76, 175, 80, 255] },
            { m: 15, color: [154, 205, 50, 255] },
            { m: 30, color: [189, 214, 102, 255] },
            { m: 60, color: [210, 201, 128, 255] },
            { m: 100, color: [201, 186, 130, 255] },
            { m: 150, color: [184, 154, 108, 255] },
            { m: 250, color: [160, 120, 80, 255] },
            { m: 400, color: [135, 105, 80, 255] },
            { m: 700, color: [120, 120, 120, 255] },
            { m: 1200, color: [150, 150, 150, 255] },
            { m: 2000, color: [185, 185, 185, 255] },
            { m: 3000, color: [225, 225, 225, 255] },
            { m: 4500, color: [245, 245, 245, 255] },
            { m: 6500, color: [255, 255, 255, 255] }
        ];
        this._elevVizStopTs = this.ELEV_VIZ_STOPS_M.map(s => ({
            t: this._elevVizTFromMeters(s.m),
            color: s.color
        }));

        // LUT state
        this._elevationLut = null;
        this._floodLut = null;
        this._floodLutWlKey = null;
        this._lutRebuilds = 0;
    }

    _elevVizTFromMeters(elevationM) {
        const e = Math.max(0, Math.min(this.ELEV_VIZ_MAX_M, elevationM));
        const s = this.ELEV_VIZ_ASINH_SCALE_M;
        return Math.asinh(e / s) / Math.asinh(this.ELEV_VIZ_MAX_M / s);
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
            return this.WATER_RGBA;
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

        const t = this._elevVizTFromMeters(elevation);

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
                    ? renderer.WATER_RGBA
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
