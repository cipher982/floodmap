/**
 * Client-side flood rendering with proper MapLibre integration
 * Uses custom protocol handler to intercept tile requests
 */

class FloodMapClient {
    constructor() {
        this.map = null;
        this.currentWaterLevel = 1.0;
        this.viewMode = 'elevation';
        this.elevationRenderer = new ElevationRenderer();
        
        // Always use client-side rendering for flood tiles
        this.setupCustomProtocol();
        console.log('🚀 Client-side rendering initialized');
        
        this.init();
    }
    
    
    setupCustomProtocol() {
        const self = this;
        
        // Register a custom protocol with MapLibre (4.7.1+ Promise-based API)
        maplibregl.addProtocol('client', async (params, abortController) => {
            try {
                // Parse the request URL
                // Format: client://flood/{z}/{x}/{y}
                const url = params.url.replace('client://', '');
                const parts = url.split('/');
                
                if ((parts[0] === 'flood' || parts[0] === 'elevation') && parts.length >= 4) {
                    const mode = parts[0];
                    const z = parseInt(parts[1]);
                    const x = parseInt(parts[2]);
                    const y = parseInt(parts[3].split('?')[0]);
                    
                    // Generate tile (logging in production can be removed)
                    
                    // Generate tile based on mode
                    const blob = await self.generateTile(z, x, y, mode, self.currentWaterLevel);
                    
                    const arrayBuffer = await blob.arrayBuffer();
                    return { data: arrayBuffer };
                } else {
                    throw new Error(`Invalid client protocol URL: ${params.url}`);
                }
            } catch (error) {
                console.error(`Failed to generate tile from ${params.url}:`, error);
                throw error;
            }
        });
        
        console.log('✅ Client protocol registered successfully');
    }
    
    async generateTile(z, x, y, mode, waterLevel = null) {
        // Load elevation data
        const elevationData = await this.elevationRenderer.loadElevationTile(z, x, y);
        
        // Debug logging (development mode only)
        if (window.DEBUG_TILES && Math.random() < 0.05) { // 5% of tiles when debugging enabled
            console.log(`🔍 Debug tile ${z}/${x}/${y}:`, {
                dataLength: elevationData.length,
                first10Values: Array.from(elevationData.slice(0, 10)),
                centerValue: elevationData[128 * 256 + 128],
                decodedCenter: this.elevationRenderer.decodeElevation(elevationData[128 * 256 + 128])
            });
        }
        
        // Create canvas
        const canvas = document.createElement('canvas');
        canvas.width = 256;
        canvas.height = 256;
        const ctx = canvas.getContext('2d', { alpha: true });
        
        // Create image data
        const imageData = ctx.createImageData(256, 256);
        const data = imageData.data;

        // Fast-path: if the entire tile is NODATA, fill with a consistent water/ocean color
        // Use FLOODED blue in flood mode so offshore tiles match per-pixel NODATA handling
        // Use OCEAN color in elevation mode
        if (this.elevationRenderer.isAllNoData(elevationData)) {
            const fillColor = (mode === 'flood')
                ? this.elevationRenderer.colors.FLOODED
                : this.elevationRenderer.OCEAN_RGBA;
            this.elevationRenderer.fillImageData(imageData, fillColor);
            ctx.putImageData(imageData, 0, 0);
            return new Promise((resolve, reject) => {
                canvas.toBlob(blob => {
                    blob ? resolve(blob) : reject(new Error(`Failed to create ${mode} tile`));
                }, 'image/png');
            });
        }
        
        // Process each pixel - simple 1:1 mapping
        let debugColorSample = null;
        for (let i = 0; i < elevationData.length; i++) {
            const elevation = this.elevationRenderer.decodeElevation(elevationData[i]);
            const color = mode === 'elevation' 
                ? this.elevationRenderer.calculateElevationColor(elevation)
                : this.elevationRenderer.calculateFloodColor(elevation, waterLevel);
            
            // Debug: sample first non-transparent color
            if (!debugColorSample && color[3] > 0) {
                debugColorSample = { 
                    raw: elevationData[i], 
                    elevation, 
                    color,
                    mode 
                };
            }
            
            const offset = i * 4;
            data[offset] = color[0];
            data[offset + 1] = color[1];
            data[offset + 2] = color[2];
            data[offset + 3] = color[3];
        }
        
        // Log debug info (development mode only)
        if (window.DEBUG_TILES && debugColorSample && Math.random() < 0.05) {
            console.log(`🎨 Color sample for tile ${z}/${x}/${y}:`, debugColorSample);
        }
        
        ctx.putImageData(imageData, 0, 0);
        
        // Convert to blob
        return new Promise((resolve, reject) => {
            canvas.toBlob(blob => {
                blob ? resolve(blob) : reject(new Error(`Failed to create ${mode} tile`));
            }, 'image/png');
        });
    }
    
    init() {
        this.initializeMap();
        this.setupEventListeners();
    }
    
    async initializeMap() {
        const config = {
            zoom: 8,
            minZoom: 0,
            maxZoom: 18
        };
        
        // Determine tile URL based on mode
        const tileUrl = this.getTileUrl();
        
        this.map = new maplibregl.Map({
            container: 'map',
            style: {
                version: 8,
                sources: {
                    'elevation-tiles': {
                        type: 'raster',
                        tiles: [tileUrl],
                        tileSize: 256,
                        scheme: 'xyz'
                    },
                    'vector-tiles': {
                        type: 'vector',
                        tiles: [window.location.origin + '/api/v1/tiles/vector/usa/{z}/{x}/{y}.pbf']
                    }
                },
                layers: [
                    {
                        id: 'background',
                        type: 'background',
                        paint: { 'background-color': '#f8f9fa' }
                    },
                    {
                        id: 'elevation',
                        type: 'raster',
                        source: 'elevation-tiles',
                        paint: { 'raster-opacity': 1.0 }
                    },
                    {
                        id: 'roads',
                        type: 'line',
                        source: 'vector-tiles',
                        'source-layer': 'transportation',
                        paint: { 'line-color': '#6b7280', 'line-width': 1 }
                    }
                ]
            },
            center: [-82.46, 27.95], // Tampa Bay
            zoom: config.zoom,
            minZoom: config.minZoom,
            maxZoom: config.maxZoom
        });
        
        this.map.addControl(new maplibregl.NavigationControl(), 'top-right');
        
        this.map.on('click', (e) => {
            this.assessLocationRisk(e.lngLat.lat, e.lngLat.lng, e.lngLat);
        });
        
        // Optional: Add tile loading listeners for debugging
    }
    
    getTileUrl() {
        if (this.viewMode === 'elevation') {
            // Client-side elevation rendering (no server requests)
            return 'client://elevation/{z}/{x}/{y}';
        } else {
            // Client-side flood rendering
            return 'client://flood/{z}/{x}/{y}';
        }
    }
    
    setupEventListeners() {
        // View mode radio buttons
        const viewModeRadios = document.querySelectorAll('input[name="view-mode"]');
        viewModeRadios.forEach(radio => {
            radio.addEventListener('change', (e) => {
                this.viewMode = e.target.value;
                this.updateViewMode();
            });
        });
        
        // Water level slider
        const waterLevelSlider = document.getElementById('water-level');
        const waterLevelDisplay = document.getElementById('water-level-display');
        const waterLevelVibe = document.getElementById('water-level-vibe');
        
        waterLevelSlider.addEventListener('input', (e) => {
            const sliderValue = parseFloat(e.target.value);
            const oldWaterLevel = this.currentWaterLevel;
            this.currentWaterLevel = this.sliderToWaterLevel(sliderValue);
            
            waterLevelDisplay.textContent = `${this.currentWaterLevel}m`;
            this.updateWaterLevelVibe(this.currentWaterLevel, waterLevelVibe);
            
            // Only update if water level actually changed
            if (oldWaterLevel !== this.currentWaterLevel) {
                this.updateFloodLayer();
            }
        });
        
        // Initialize with default value
        this.currentWaterLevel = this.sliderToWaterLevel(30);
        waterLevelDisplay.textContent = `${this.currentWaterLevel}m`;
        this.updateWaterLevelVibe(this.currentWaterLevel, waterLevelVibe);
        
        // Find location button
        document.getElementById('find-location').addEventListener('click', () => {
            this.findUserLocation();
        });
        
        // Status display can be added for debugging if needed
        
        // Wait for map to be loaded before initial update
        if (this.map && this.map.loaded()) {
            this.updateViewMode();
        } else {
            this.map.on('load', () => {
                this.updateViewMode();
            });
        }
    }
    
    
    updateViewMode() {
        const waterLevelControls = document.getElementById('water-level-controls');
        
        if (this.viewMode === 'elevation') {
            waterLevelControls.style.opacity = '0';
            waterLevelControls.style.transform = 'translateY(-10px)';
            setTimeout(() => {
                waterLevelControls.style.display = 'none';
            }, 200);
        } else {
            waterLevelControls.style.display = 'block';
            setTimeout(() => {
                waterLevelControls.style.opacity = '1';
                waterLevelControls.style.transform = 'translateY(0)';
            }, 10);
        }
        
        this.updateFloodLayer();
    }
    
    updateFloodLayer() {
        if (!this.map || !this.map.loaded()) {
            return;
        }
        
        const source = this.map.getSource('elevation-tiles');
        if (!source) return;
        
        if (this.viewMode === 'flood') {
            // Clear the renderer cache to force re-render with new water level
            if (this.elevationRenderer) {
                this.elevationRenderer.clearRenderedCache();
            }
            
            source.setTiles(['client://flood/{z}/{x}/{y}']);
        } else {
            source.setTiles(['client://elevation/{z}/{x}/{y}']);
        }
    }
    
    sliderToWaterLevel(sliderValue) {
        const waterLevel = 0.1 * Math.pow(10, sliderValue / 25);
        return Math.round(waterLevel * 10) / 10;
    }
    
    getTileCoordinates(lat, lng, zoom) {
        // Convert lat/lng to tile coordinates using Web Mercator projection
        const n = Math.pow(2, zoom);
        const x = Math.floor(n * ((lng + 180) / 360));
        const latRad = lat * Math.PI / 180;
        const y = Math.floor(n * (1 - (Math.log(Math.tan(latRad) + (1 / Math.cos(latRad))) / Math.PI)) / 2);
        return { x, y };
    }
    
    updateWaterLevelVibe(waterLevel, vibeElement) {
        vibeElement.className = '';
        
        let vibeText = '';
        let vibeClass = '';
        
        if (waterLevel <= 2) {
            vibeText = 'Normal';
            vibeClass = 'vibe-normal';
        } else if (waterLevel <= 5) {
            vibeText = 'Concerning';
            vibeClass = 'vibe-concerning';
        } else if (waterLevel <= 20) {
            vibeText = 'Dangerous';
            vibeClass = 'vibe-dangerous';
        } else if (waterLevel <= 100) {
            vibeText = 'EXTREME';
            vibeClass = 'vibe-extreme';
        } else {
            vibeText = 'APOCALYPTIC';
            vibeClass = 'vibe-apocalyptic';
        }
        
        vibeElement.textContent = vibeText;
        vibeElement.className = vibeClass;
    }
    
    async findUserLocation() {
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                (position) => {
                    const lat = position.coords.latitude;
                    const lng = position.coords.longitude;
                    
                    this.map.setCenter([lng, lat]);
                    this.map.setZoom(this.map.getMaxZoom());
                    this.assessLocationRisk(lat, lng);
                },
                (error) => {
                    console.warn('Geolocation error:', error);
                    alert('Could not get your location. Please click on the map instead.');
                }
            );
        } else {
            alert('Geolocation is not supported by this browser.');
        }
    }
    
    async assessLocationRisk(lat, lng, lngLat = null) {
        try {
            // Calculate tile coordinates for current zoom level if lngLat provided
            let tileInfo = '';
            if (lngLat && this.map) {
                const zoom = Math.floor(this.map.getZoom());
                const tileCoords = this.getTileCoordinates(lat, lng, zoom);
                const tilePath = `/api/v1/tiles/elevation-data/${zoom}/${tileCoords.x}/${tileCoords.y}.u16`;
                tileInfo = `🗂️ Tile: ${zoom}/${tileCoords.x}/${tileCoords.y} (${tilePath})`;
            }
            
            const response = await fetch('/api/risk/location', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ latitude: lat, longitude: lng })
            });
            
            const data = await response.json();
            // Add tile info to data for display
            data.tileInfo = tileInfo;
            
            this.updateRiskPanel(data);
            this.updateLocationInfo(data);
            this.addLocationMarker(lng, lat, data);
            
        } catch (error) {
            console.error('Risk assessment error:', error);
        }
    }
    
    updateLocationInfo(data) {
        const locationInfo = document.getElementById('location-info');
        locationInfo.innerHTML = `
            📍 ${data.latitude.toFixed(4)}°, ${data.longitude.toFixed(4)}°
            ${data.elevation_m ? `• ${data.elevation_m}m elevation` : ''}
            ${data.tileInfo ? `<br>${data.tileInfo}` : ''}
        `;
    }
    
    updateRiskPanel(data) {
        const riskDetails = document.getElementById('risk-details');
        const riskClass = `risk-${data.flood_risk_level}`;
        
        riskDetails.innerHTML = `
            <div class="risk-summary ${riskClass}">
                <strong>Risk Level: ${data.flood_risk_level.toUpperCase()}</strong>
            </div>
            <p><strong>Location:</strong> ${data.latitude.toFixed(4)}°, ${data.longitude.toFixed(4)}°</p>
            ${data.elevation_m ? `<p><strong>Elevation:</strong> ${data.elevation_m}m</p>` : ''}
            <p><strong>Water Level:</strong> ${data.water_level_m}m</p>
            <p><strong>Assessment:</strong> ${data.risk_description}</p>
            ${data.tileInfo ? `<p><strong>Debug:</strong> ${data.tileInfo}</p>` : ''}
        `;
    }
    
    addLocationMarker(lng, lat, data) {
        const existingMarkers = document.querySelectorAll('.maplibregl-marker');
        existingMarkers.forEach(marker => marker.remove());
        
        const marker = new maplibregl.Marker({ color: '#ef4444' })
            .setLngLat([lng, lat])
            .setPopup(new maplibregl.Popup().setHTML(`
                <div>
                    <strong>Flood Risk: ${data.flood_risk_level}</strong><br>
                    Elevation: ${data.elevation_m || 'Unknown'}m<br>
                    ${data.risk_description}
                </div>
            `))
            .addTo(this.map);
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    window.floodMap = new FloodMapClient();
});
