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
     * Fill ImageData with solid color
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

// Worker instance
const renderer = new WorkerElevationRenderer();

// Message handler
self.onmessage = function(e) {
    const { type, jobId, data } = e.data;

    if (type === 'render') {
        try {
            const { elevationData, mode, waterLevel, width, height } = data;

            // Convert back to Uint16Array
            const elevationArray = new Uint16Array(elevationData);

            // Fast-path: check if entire tile is NODATA
            if (renderer.isAllNoData(elevationArray)) {
                const fillColor = (mode === 'flood')
                    ? renderer.colors.FLOODED
                    : renderer.OCEAN_RGBA;

                // Create filled ImageData
                const imageData = new ImageData(width, height);
                renderer.fillImageData(imageData, fillColor);

                // Send back the ImageData buffer
                self.postMessage({
                    type: 'complete',
                    jobId,
                    imageData: imageData.data.buffer
                }, [imageData.data.buffer]);
                return;
            }

            // Create ImageData for processing
            const imageData = new ImageData(width, height);
            const pixelData = imageData.data;

            // Process each pixel
            for (let i = 0; i < elevationArray.length; i++) {
                const elevation = renderer.decodeElevation(elevationArray[i]);
                const color = mode === 'elevation'
                    ? renderer.calculateElevationColor(elevation)
                    : renderer.calculateFloodColor(elevation, waterLevel);

                const offset = i * 4;
                pixelData[offset] = color[0];
                pixelData[offset + 1] = color[1];
                pixelData[offset + 2] = color[2];
                pixelData[offset + 3] = color[3];
            }

            // Send back the ImageData buffer (transfer ownership for performance)
            self.postMessage({
                type: 'complete',
                jobId,
                imageData: imageData.data.buffer
            }, [imageData.data.buffer]);

        } catch (error) {
            self.postMessage({
                type: 'error',
                jobId,
                error: error.message
            });
        }
    }
};

// Signal that worker is ready
self.postMessage({ type: 'ready' });
