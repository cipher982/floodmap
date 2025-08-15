/**
 * Simplified client-side flood rendering implementation
 * Uses dynamic tile generation with blob URLs
 */

class FloodMapClient {
    constructor() {
        this.map = null;
        this.currentWaterLevel = 1.0;
        this.viewMode = 'elevation';
        this.elevationRenderer = null;
        this.tileUrls = new Map();
        this.useClientRendering = this.checkFeatureFlag();
        
        if (this.useClientRendering) {
            this.elevationRenderer = new ElevationRenderer();
            console.log('🚀 Client-side rendering enabled');
            
            // Override tile loading
            this.setupTileInterception();
        }
        
        this.init();
    }
    
    checkFeatureFlag() {
        const params = new URLSearchParams(window.location.search);
        if (params.get('client') === 'false') return false;
        if (params.get('client') === 'true') return true;
        // Default to client-side for flood mode
        return true;
    }
    
    setupTileInterception() {
        // Store original fetch
        const originalFetch = window.fetch;
        const self = this;
        
        // Override fetch to intercept tile requests
        window.fetch = async function(url, ...args) {
            // Check if this is a flood tile request
            if (typeof url === 'string' && url.includes('/api/tiles/elevation/') && url.includes('.png')) {
                // Parse tile coordinates from URL
                const match = url.match(/elevation\/([\d.]+)\/(\d+)\/(\d+)\/(\d+)\.png/);
                if (match) {
                    const [, waterLevel, z, x, y] = match;
                    
                    // Check if we should use client rendering
                    if (self.useClientRendering && self.viewMode === 'flood') {
                        // Generate tile client-side
                        const blob = await self.generateTileBlob(
                            parseInt(z), 
                            parseInt(x), 
                            parseInt(y), 
                            parseFloat(waterLevel)
                        );
                        
                        // Return fake response with blob
                        return new Response(blob, {
                            status: 200,
                            headers: { 'Content-Type': 'image/png' }
                        });
                    }
                }
            }
            
            // Fall back to original fetch
            return originalFetch.apply(this, [url, ...args]);
        };
    }
    
    async generateTileBlob(z, x, y, waterLevel) {
        try {
            // Load elevation data
            const elevationData = await this.elevationRenderer.loadElevationTile(z, x, y);
            
            // Create canvas
            const canvas = document.createElement('canvas');
            canvas.width = 256;
            canvas.height = 256;
            const ctx = canvas.getContext('2d', { alpha: true });
            
            // Create image data
            const imageData = ctx.createImageData(256, 256);
            const data = imageData.data;
            
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
            
            // Convert to blob
            return new Promise(resolve => {
                canvas.toBlob(resolve, 'image/png');
            });
            
        } catch (error) {
            console.error(`Failed to generate tile ${z}/${x}/${y}:`, error);
            // Return transparent tile
            const canvas = document.createElement('canvas');
            canvas.width = 256;
            canvas.height = 256;
            return new Promise(resolve => {
                canvas.toBlob(resolve, 'image/png');
            });
        }
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
        
        this.map = new maplibregl.Map({
            container: 'map',
            style: {
                version: 8,
                sources: {
                    'elevation-tiles': {
                        type: 'raster',
                        tiles: [this.getElevationTileURL()],
                        tileSize: 256
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
            this.assessLocationRisk(e.lngLat.lat, e.lngLat.lng);
        });
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
            this.currentWaterLevel = this.sliderToWaterLevel(sliderValue);
            
            waterLevelDisplay.textContent = `${this.currentWaterLevel}m`;
            this.updateWaterLevelVibe(this.currentWaterLevel, waterLevelVibe);
            
            // Clear client-side cache when water level changes
            if (this.elevationRenderer) {
                this.elevationRenderer.clearRenderedCache();
            }
            
            this.updateFloodLayer();
        });
        
        // Initialize with default value
        this.currentWaterLevel = this.sliderToWaterLevel(30);
        waterLevelDisplay.textContent = `${this.currentWaterLevel}m`;
        this.updateWaterLevelVibe(this.currentWaterLevel, waterLevelVibe);
        
        // Find location button
        document.getElementById('find-location').addEventListener('click', () => {
            this.findUserLocation();
        });
        
        // Show client-side status
        if (this.useClientRendering) {
            this.showClientStatus();
        }
        
        this.updateViewMode();
    }
    
    showClientStatus() {
        const status = document.createElement('div');
        status.style.position = 'fixed';
        status.style.top = '10px';
        status.style.left = '50%';
        status.style.transform = 'translateX(-50%)';
        status.style.background = '#4CAF50';
        status.style.color = 'white';
        status.style.padding = '5px 10px';
        status.style.borderRadius = '4px';
        status.style.zIndex = '1000';
        status.style.fontSize = '12px';
        status.textContent = '⚡ Client-side rendering active';
        document.body.appendChild(status);
        
        // Auto-hide after 3 seconds
        setTimeout(() => status.remove(), 3000);
    }
    
    getElevationTileURL() {
        return this.viewMode === 'elevation' 
            ? '/api/tiles/topographical/{z}/{x}/{y}.png'
            : `/api/tiles/elevation/${this.currentWaterLevel}/{z}/{x}/{y}.png`;
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
        // Force tile refresh by updating the source
        this.map.getSource('elevation-tiles').setTiles([this.getElevationTileURL()]);
    }
    
    sliderToWaterLevel(sliderValue) {
        const waterLevel = 0.1 * Math.pow(10, sliderValue / 25);
        return Math.round(waterLevel * 10) / 10;
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
    
    async assessLocationRisk(lat, lng) {
        try {
            const response = await fetch('/api/risk/location', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ latitude: lat, longitude: lng })
            });
            
            const data = await response.json();
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