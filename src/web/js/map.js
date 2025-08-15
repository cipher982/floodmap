/**
 * Clean MapLibre implementation for flood risk mapping
 * No framework dependencies - pure JavaScript
 */

class FloodMap {
    constructor() {
        this.map = null;
        this.currentWaterLevel = 1.0;
        this.viewMode = 'elevation'; // 'elevation' or 'flood'
        
        // Client-side rendering configuration
        this.clientSideRendering = this.checkClientSideSupport();
        this.elevationRenderer = null;
        this.customSource = null;
        this.visibleTiles = new Set();
        
        // Initialize elevation renderer if supported
        if (this.clientSideRendering) {
            this.elevationRenderer = new ElevationRenderer();
            console.log('🚀 Client-side flood rendering enabled');
        } else {
            console.log('📡 Using server-side flood rendering');
        }
        
        this.init();
    }

    init() {
        this.initializeMap();
        this.setupEventListeners();
        // Don't automatically load user location - keep Tampa Bay as default
        // this.loadUserLocation();
    }

    async initializeMap() {
        // Simple static configuration - elevation tiles work everywhere
        const config = {
            zoom: 8,
            minZoom: 0,
            maxZoom: 18
        };
        
        console.log(`Configuring map: zoom=${config.zoom}, range=${config.minZoom}-${config.maxZoom}`);

        // Create map with clean, simple architecture
        this.map = new maplibregl.Map({
            container: 'map',
            style: {
                version: 8,
                sources: {
                    'elevation-tiles': {
                        type: 'raster',
                        tiles: this.clientSideRendering ? [] : [this.getElevationTileURL()],
                        tileSize: 256
                    },
                    'vector-tiles': {
                        type: 'vector',
                        tiles: [window.location.origin + '/api/v1/tiles/vector/usa/{z}/{x}/{y}.pbf']
                    }
                },
                layers: [
                    // Background
                    {
                        id: 'background',
                        type: 'background',
                        paint: { 'background-color': '#f8f9fa' }
                    },
                    // Elevation tiles are authoritative for ALL water
                    {
                        id: 'elevation',
                        type: 'raster',
                        source: 'elevation-tiles',
                        paint: { 'raster-opacity': 1.0 }
                    },
                    // Optional: Roads for navigation
                    {
                        id: 'roads',
                        type: 'line',
                        source: 'vector-tiles',
                        'source-layer': 'transportation',
                        paint: { 'line-color': '#6b7280', 'line-width': 1 }
                    }
                ]
            },
            center: [-82.46, 27.95], // Tampa Bay, Florida
            zoom: config.zoom,
            minZoom: config.minZoom,
            maxZoom: config.maxZoom
        });

        // Add navigation controls
        this.map.addControl(new maplibregl.NavigationControl(), 'top-right');

        // Add click handler for risk assessment
        this.map.on('click', (e) => {
            this.assessLocationRisk(e.lngLat.lat, e.lngLat.lng);
        });
        
        // Set up client-side rendering if enabled
        if (this.clientSideRendering) {
            this.setupClientSideRendering();
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

        // Water level slider (logarithmic)
        const waterLevelSlider = document.getElementById('water-level');
        const waterLevelDisplay = document.getElementById('water-level-display');
        const waterLevelVibe = document.getElementById('water-level-vibe');
        
        waterLevelSlider.addEventListener('input', (e) => {
            // Convert slider value (0-100) to logarithmic water level (0.1-1000m)
            const sliderValue = parseFloat(e.target.value);
            this.currentWaterLevel = this.sliderToWaterLevel(sliderValue);
            
            // Update display
            waterLevelDisplay.textContent = `${this.currentWaterLevel}m`;
            this.updateWaterLevelVibe(this.currentWaterLevel, waterLevelVibe);
            
            // Update map
            this.updateFloodLayer();
        });
        
        // Initialize with default value
        this.currentWaterLevel = this.sliderToWaterLevel(30); // Default to ~1m
        waterLevelDisplay.textContent = `${this.currentWaterLevel}m`;
        this.updateWaterLevelVibe(this.currentWaterLevel, waterLevelVibe);

        // Find location button
        document.getElementById('find-location').addEventListener('click', () => {
            this.findUserLocation();
        });

        // Initialize UI state
        this.updateViewMode();
    }

    getElevationTileURL() {
        // Simple template strings - no complex switching logic
        return this.viewMode === 'elevation' 
            ? '/api/tiles/topographical/{z}/{x}/{y}.png'
            : `/api/tiles/elevation/${this.currentWaterLevel}/{z}/{x}/{y}.png`;
    }

    updateViewMode() {
        // Show/hide water level controls based on mode with smooth transition
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

        // Update map tiles
        this.updateFloodLayer();
    }

    sliderToWaterLevel(sliderValue) {
        // Convert slider value (0-100) to logarithmic water level (0.1-1000m)
        // Using exponential mapping: y = 0.1 * (10^(x/25))
        const waterLevel = 0.1 * Math.pow(10, sliderValue / 25);
        return Math.round(waterLevel * 10) / 10; // Round to 1 decimal place
    }

    updateWaterLevelVibe(waterLevel, vibeElement) {
        // Remove all existing vibe classes
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

    updateFloodLayer() {
        if (this.clientSideRendering && this.viewMode === 'flood') {
            // Client-side rendering for flood mode
            this.updateClientSideTiles();
        } else {
            // Server-side rendering (elevation mode or fallback)
            this.map.getSource('elevation-tiles').setTiles([this.getElevationTileURL()]);
        }
    }

    async loadUserLocation() {
        try {
            const response = await fetch('/api/risk/ip');
            const data = await response.json();
            
            this.map.setCenter([data.longitude, data.latitude]);
            this.updateLocationInfo(data);
            this.updateRiskPanel(data);
        } catch (error) {
            console.warn('Could not load user location:', error);
        }
    }

    findUserLocation() {
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                (position) => {
                    const lat = position.coords.latitude;
                    const lng = position.coords.longitude;
                    
                    this.map.setCenter([lng, lat]);
                    // Use maximum available zoom level for location
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
            
            // Add marker
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
        // Remove existing markers
        const existingMarkers = document.querySelectorAll('.maplibregl-marker');
        existingMarkers.forEach(marker => marker.remove());

        // Add new marker
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
    
    // ============================================================================
    // Client-Side Rendering Methods
    // ============================================================================
    
    checkClientSideSupport() {
        // Check for required browser features
        const hasCanvas = !!document.createElement('canvas').getContext;
        const hasTypedArrays = typeof Uint16Array !== 'undefined';
        const hasFetch = typeof fetch !== 'undefined';
        
        // Check URL parameters for feature flag
        const params = new URLSearchParams(window.location.search);
        const forceServer = params.get('server') === 'true';
        const forceClient = params.get('client') === 'true';
        
        if (forceServer) return false;
        if (forceClient) return true;
        
        // Default: use client-side if supported
        return hasCanvas && hasTypedArrays && hasFetch;
    }
    
    setupClientSideRendering() {
        // Track tile visibility
        this.map.on('moveend', () => {
            if (this.viewMode === 'flood' && this.clientSideRendering) {
                this.updateClientSideTiles();
            }
        });
        
        // Initial load if in flood mode
        if (this.viewMode === 'flood') {
            this.updateClientSideTiles();
        }
    }
    
    async updateClientSideTiles() {
        if (!this.elevationRenderer) return;
        
        const startTime = performance.now();
        
        // Clear rendered cache on water level change
        if (this.lastWaterLevel !== this.currentWaterLevel) {
            this.elevationRenderer.clearRenderedCache();
            this.lastWaterLevel = this.currentWaterLevel;
        }
        
        // Get current viewport bounds and zoom
        const bounds = this.map.getBounds();
        const zoom = Math.floor(this.map.getZoom());
        
        // Get visible tiles
        const tiles = this.getVisibleTiles(bounds, zoom);
        
        // Update each tile
        const updatePromises = tiles.map(async ({z, x, y}) => {
            try {
                // Load elevation data
                const elevationData = await this.elevationRenderer.loadElevationTile(z, x, y);
                
                // Render flood overlay
                const tileKey = `${z}/${x}/${y}`;
                const tileDataUrl = this.elevationRenderer.renderFloodTile(
                    elevationData, 
                    this.currentWaterLevel,
                    tileKey
                );
                
                // Update the tile in the map
                this.updateTileInMap(z, x, y, tileDataUrl);
                
            } catch (error) {
                console.error(`Failed to render tile ${z}/${x}/${y}:`, error);
            }
        });
        
        await Promise.all(updatePromises);
        
        const totalTime = performance.now() - startTime;
        console.debug(`\ud83c\udfa8 Rendered ${tiles.length} tiles in ${totalTime.toFixed(1)}ms`);
        
        // Log stats
        const stats = this.elevationRenderer.getStats();
        console.debug('Renderer stats:', stats);
    }
    
    getVisibleTiles(bounds, zoom) {
        const tiles = [];
        
        // Convert bounds to tile coordinates
        const nw = this.lngLatToTile(bounds.getNorthWest().lng, bounds.getNorthWest().lat, zoom);
        const se = this.lngLatToTile(bounds.getSouthEast().lng, bounds.getSouthEast().lat, zoom);
        
        // Add buffer for smoother panning
        const buffer = 1;
        const minX = Math.max(0, Math.floor(nw.x) - buffer);
        const maxX = Math.min(Math.pow(2, zoom) - 1, Math.floor(se.x) + buffer);
        const minY = Math.max(0, Math.floor(nw.y) - buffer);
        const maxY = Math.min(Math.pow(2, zoom) - 1, Math.floor(se.y) + buffer);
        
        // Collect all visible tiles
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
    
    updateTileInMap(z, x, y, dataUrl) {
        // Create a unique tile URL that MapLibre will recognize
        const tileId = `client-tile-${z}-${x}-${y}-${this.currentWaterLevel}`;
        
        // Update the raster source with the rendered tile
        // This is a workaround to inject custom tiles into MapLibre
        const source = this.map.getSource('elevation-tiles');
        if (source) {
            // Store the data URL in a way that MapLibre can access it
            // We'll use a custom protocol handler or canvas source
            this.injectCustomTile(source, z, x, y, dataUrl);
        }
    }
    
    injectCustomTile(source, z, x, y, dataUrl) {
        // MapLibre doesn't directly support injecting individual tiles
        // We need to use a different approach: Canvas source or custom layer
        
        // For now, we'll update the entire source with a custom tile function
        // This is a simplified approach - in production, we'd use a custom layer
        
        if (!this.customTileCache) {
            this.customTileCache = new Map();
        }
        
        const key = `${z}/${x}/${y}`;
        this.customTileCache.set(key, dataUrl);
        
        // Update the source tiles to use our custom tiles
        const tiles = [`canvas://flood/{z}/{x}/{y}`];
        source.setTiles(tiles);
        
        // Override the tile loading mechanism
        if (!this.tileLoadingOverridden) {
            this.overrideTileLoading();
            this.tileLoadingOverridden = true;
        }
    }
    
    overrideTileLoading() {
        // This is a simplified approach
        // In a production implementation, we would:
        // 1. Create a custom MapLibre layer
        // 2. Use Canvas or WebGL directly
        // 3. Or use a service worker to intercept tile requests
        
        // For now, fall back to updating tiles through URL changes
        const source = this.map.getSource('elevation-tiles');
        if (source && this.customTileCache && this.customTileCache.size > 0) {
            // Create blob URLs for our rendered tiles
            const tiles = [];
            this.customTileCache.forEach((dataUrl, key) => {
                // Convert data URL to blob URL (more efficient)
                fetch(dataUrl)
                    .then(res => res.blob())
                    .then(blob => {
                        const blobUrl = URL.createObjectURL(blob);
                        // Store for cleanup
                        if (!this.blobUrls) this.blobUrls = [];
                        this.blobUrls.push(blobUrl);
                    });
            });
            
            // For immediate rendering, use data URLs directly
            // This works but is less efficient than blob URLs
            source.tiles = [
                (x, y, z) => {
                    const key = `${z}/${x}/${y}`;
                    return this.customTileCache.get(key) || this.getElevationTileURL();
                }
            ];
        }
    }
    
    cleanup() {
        // Clean up blob URLs to prevent memory leaks
        if (this.blobUrls) {
            this.blobUrls.forEach(url => URL.revokeObjectURL(url));
            this.blobUrls = [];
        }
        
        // Clear caches
        if (this.elevationRenderer) {
            this.elevationRenderer.clearAllCaches();
        }
    }
}

// Initialize the map when the page loads
document.addEventListener('DOMContentLoaded', () => {
    new FloodMap();
});