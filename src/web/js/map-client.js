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
        console.log('🚀 Client-side flood rendering initialized');
        
        this.init();
    }
    
    
    setupCustomProtocol() {
        const self = this;
        
        // Register a custom protocol with MapLibre
        maplibregl.addProtocol('client', (params, callback) => {
            // Parse the request URL
            // Format: client://flood/{z}/{x}/{y}
            const url = params.url.replace('client://', '');
            const parts = url.split('/');
            
            if (parts[0] === 'flood' && parts.length >= 4) {
                const z = parseInt(parts[1]);
                const x = parseInt(parts[2]);
                const y = parseInt(parts[3].split('?')[0]);
                
                // ALWAYS use the current water level from the slider
                // This ensures tiles are re-rendered with the latest value
                const waterLevel = self.currentWaterLevel;
                
                // Generate tile asynchronously
                self.generateClientTile(z, x, y, waterLevel)
                    .then(blob => {
                        // Convert blob to array buffer for MapLibre
                        blob.arrayBuffer().then(buffer => {
                            callback(null, buffer, null, null);
                        });
                    })
                    .catch(error => {
                        console.error(`Failed to generate tile ${z}/${x}/${y}:`, error);
                        callback(error);
                    });
                    
                // Return true to indicate async handling
                return true;
            }
            
            callback(new Error('Invalid client protocol URL'));
            return true;
        });
    }
    
    async generateClientTile(z, x, y, waterLevel) {
        // Load elevation data (cached after first load)
        const elevationData = await this.elevationRenderer.loadElevationTile(z, x, y);
        
        // Create canvas for rendering - no caching, always fresh render
        const canvas = document.createElement('canvas');
        canvas.width = 256;
        canvas.height = 256;
        const ctx = canvas.getContext('2d', { alpha: true });
        
        // Create image data
        const imageData = ctx.createImageData(256, 256);
        const data = imageData.data;
        
        // Process each pixel with the current water level
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
        
        // Convert to blob - always fresh, no caching
        return new Promise((resolve, reject) => {
            canvas.toBlob(blob => {
                if (blob) {
                    resolve(blob);
                } else {
                    reject(new Error('Failed to create blob'));
                }
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
            this.assessLocationRisk(e.lngLat.lat, e.lngLat.lng);
        });
        
        // Log tile requests for debugging
        this.map.on('dataloading', (e) => {
            if (e.sourceId === 'elevation-tiles' && e.tile) {
                console.log(`Loading tile: ${e.tile.tileID.canonical.z}/${e.tile.tileID.canonical.x}/${e.tile.tileID.canonical.y}`);
            }
        });
    }
    
    getTileUrl() {
        if (this.viewMode === 'elevation') {
            // Server for elevation/topographical view
            return '/api/tiles/topographical/{z}/{x}/{y}.png';
        } else {
            // Always use client-side rendering for flood view
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
        
        // Show client-side status
        this.showClientStatus();
        
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
        status.textContent = '⚡ Client-side rendering active (0 network requests)';
        document.body.appendChild(status);
        
        // Show stats
        setTimeout(() => {
            if (this.elevationRenderer) {
                const stats = this.elevationRenderer.getStats();
                status.textContent = `⚡ Client: ${stats.tilesLoaded} tiles cached, ${stats.tilesRendered} rendered`;
            }
        }, 5000);
        
        // Keep status visible
        setTimeout(() => {
            status.style.opacity = '0.7';
        }, 8000);
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
        if (this.viewMode === 'flood') {
            // Clear the renderer cache to force re-render with new water level
            if (this.elevationRenderer) {
                this.elevationRenderer.clearRenderedCache();
            }
            
            // Switch to client-side rendering protocol
            this.map.getSource('elevation-tiles').setTiles(['client://flood/{z}/{x}/{y}']);
        } else {
            // Topographical view - always from server
            this.map.getSource('elevation-tiles').setTiles(['/api/tiles/topographical/{z}/{x}/{y}.png']);
        }
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