/**
 * Custom MapLibre layer for client-side flood rendering
 * Uses Canvas API to render flood tiles from elevation data
 */

class ClientFloodLayer {
    constructor(elevationRenderer) {
        this.id = 'client-flood-layer';
        this.type = 'custom';
        this.renderingMode = '2d';
        this.elevationRenderer = elevationRenderer;
        this.tiles = new Map(); // Store rendered tiles
        this.canvases = new Map(); // Store canvas elements
    }
    
    onAdd(map, gl) {
        this.map = map;
        this.gl = gl;
        
        // Create a container for our tiles
        const mapContainer = map.getCanvasContainer();
        this.container = document.createElement('div');
        this.container.className = 'client-flood-tiles';
        this.container.style.position = 'absolute';
        this.container.style.width = '100%';
        this.container.style.height = '100%';
        this.container.style.pointerEvents = 'none';
        mapContainer.appendChild(this.container);
    }
    
    render(gl, matrix) {
        // Get current viewport
        const zoom = Math.floor(this.map.getZoom());
        const bounds = this.map.getBounds();
        
        // Calculate visible tiles
        const tiles = this.getVisibleTiles(bounds, zoom);
        
        // Remove old tiles
        this.cleanupOldTiles(tiles);
        
        // Render each tile
        tiles.forEach(({z, x, y}) => {
            this.renderTile(z, x, y);
        });
    }
    
    async renderTile(z, x, y) {
        const key = `${z}/${x}/${y}`;
        
        // Check if already rendered
        if (this.tiles.has(key)) {
            return;
        }
        
        // Mark as rendering
        this.tiles.set(key, 'loading');
        
        try {
            // Load elevation data
            const elevationData = await this.elevationRenderer.loadElevationTile(z, x, y);
            
            // Get current water level from map
            const waterLevel = this.map.floodMap?.currentWaterLevel || 1.0;
            
            // Render to canvas
            const canvas = this.createTileCanvas(z, x, y);
            this.renderFloodToCanvas(canvas, elevationData, waterLevel);
            
            // Mark as complete
            this.tiles.set(key, 'loaded');
            
        } catch (error) {
            console.error(`Failed to render tile ${key}:`, error);
            this.tiles.delete(key);
        }
    }
    
    createTileCanvas(z, x, y) {
        const key = `${z}/${x}/${y}`;
        
        // Reuse existing canvas if available
        if (this.canvases.has(key)) {
            return this.canvases.get(key);
        }
        
        // Create new canvas
        const canvas = document.createElement('canvas');
        canvas.width = 256;
        canvas.height = 256;
        canvas.style.position = 'absolute';
        canvas.style.imageRendering = 'pixelated'; // Prevent blur
        
        // Position the canvas
        this.positionCanvas(canvas, z, x, y);
        
        // Add to container
        this.container.appendChild(canvas);
        this.canvases.set(key, canvas);
        
        return canvas;
    }
    
    positionCanvas(canvas, z, x, y) {
        // Calculate pixel position based on tile coordinates
        const tileSize = 256;
        const scale = this.map.getZoom() - z;
        const factor = Math.pow(2, scale);
        
        // Get map center and convert to pixel coordinates
        const center = this.map.project(this.map.getCenter());
        const worldSize = tileSize * Math.pow(2, z);
        
        // Calculate tile position in pixels
        const left = (x * tileSize - center.x + this.map.getCanvas().width / 2) * factor;
        const top = (y * tileSize - center.y + this.map.getCanvas().height / 2) * factor;
        
        // Apply transform
        canvas.style.transform = `translate(${left}px, ${top}px) scale(${factor})`;
        canvas.style.transformOrigin = 'top left';
    }
    
    renderFloodToCanvas(canvas, elevationData, waterLevel) {
        const ctx = canvas.getContext('2d', { alpha: true });
        const imageData = ctx.createImageData(256, 256);
        const data = imageData.data;
        
        // Color constants
        const colors = {
            SAFE: [76, 175, 80, 60],
            CAUTION: [255, 193, 7, 100],
            DANGER: [244, 67, 54, 150],
            FLOODED: [33, 150, 243, 180]
        };
        
        // Process each pixel
        for (let i = 0; i < elevationData.length; i++) {
            const elevation = this.elevationRenderer.decodeElevation(elevationData[i]);
            const color = this.elevationRenderer.calculateFloodColor(elevation, waterLevel);
            
            const offset = i * 4;
            data[offset] = color[0];
            data[offset + 1] = color[1];
            data[offset + 2] = color[2];
            data[offset + 3] = color[3];
        }
        
        ctx.putImageData(imageData, 0, 0);
    }
    
    getVisibleTiles(bounds, zoom) {
        const tiles = [];
        
        // Convert bounds to tile coordinates
        const nw = this.lngLatToTile(bounds.getNorthWest().lng, bounds.getNorthWest().lat, zoom);
        const se = this.lngLatToTile(bounds.getSouthEast().lng, bounds.getSouthEast().lat, zoom);
        
        const minX = Math.max(0, Math.floor(nw.x));
        const maxX = Math.min(Math.pow(2, zoom) - 1, Math.floor(se.x));
        const minY = Math.max(0, Math.floor(nw.y));
        const maxY = Math.min(Math.pow(2, zoom) - 1, Math.floor(se.y));
        
        for (let x = minX; x <= maxX; x++) {
            for (let y = minY; y <= maxY; y++) {
                tiles.push({ z: zoom, x, y });
            }
        }
        
        return tiles;
    }
    
    lngLatToTile(lng, lat, zoom) {
        const n = Math.pow(2, zoom);
        const x = ((lng + 180) / 360) * n;
        const latRad = lat * Math.PI / 180;
        const y = (1 - Math.asinh(Math.tan(latRad)) / Math.PI) / 2 * n;
        return { x, y };
    }
    
    cleanupOldTiles(currentTiles) {
        const currentKeys = new Set(currentTiles.map(t => `${t.z}/${t.x}/${t.y}`));
        
        // Remove tiles that are no longer visible
        this.canvases.forEach((canvas, key) => {
            if (!currentKeys.has(key)) {
                canvas.remove();
                this.canvases.delete(key);
                this.tiles.delete(key);
            }
        });
    }
    
    updateWaterLevel(waterLevel) {
        // Clear all tiles to force re-render
        this.tiles.clear();
        this.canvases.forEach(canvas => {
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, 256, 256);
        });
        
        // Trigger re-render
        this.map.triggerRepaint();
    }
    
    onRemove() {
        // Clean up
        if (this.container) {
            this.container.remove();
        }
        this.tiles.clear();
        this.canvases.clear();
    }
}

// Export for use
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ClientFloodLayer;
}