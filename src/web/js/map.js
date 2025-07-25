/**
 * Clean MapLibre implementation for flood risk mapping
 * No framework dependencies - pure JavaScript
 */

class FloodMap {
    constructor() {
        this.map = null;
        this.currentWaterLevel = 1.0;
        this.viewMode = 'elevation'; // 'elevation' or 'flood'
        this.init();
    }

    init() {
        this.initializeMap();
        this.setupEventListeners();
        this.loadUserLocation();
    }

    async initializeMap() {
        // Fetch dynamic tile metadata
        let metadata;
        try {
            const response = await fetch('/api/v1/tiles/metadata');
            metadata = await response.json();
        } catch (error) {
            console.warn('Could not fetch tile metadata, using defaults:', error);
            metadata = {
                vector_tiles: { min_zoom: 0, max_zoom: 4, available_zoom_levels: [0,1,2,3,4] },
                elevation_tiles: { min_zoom: 8, max_zoom: 14 }
            };
        }

        // Determine best zoom configuration
        const vectorZoom = metadata.vector_tiles;
        const hasVectorTiles = vectorZoom.available_zoom_levels && vectorZoom.available_zoom_levels.length > 0;
        
        // Choose initial zoom and bounds based on available data
        const initialZoom = hasVectorTiles ? Math.min(vectorZoom.max_zoom, 8) : 8;
        const minZoom = hasVectorTiles ? vectorZoom.min_zoom : 0;
        const maxZoom = hasVectorTiles ? vectorZoom.max_zoom : 4;
        
        console.log(`Vector tiles: ${vectorZoom.min_zoom}-${vectorZoom.max_zoom}`);
        console.log(`Setting map bounds: ${minZoom}-${maxZoom}, initial: ${initialZoom}`);
        
        console.log(`Configuring map: zoom=${initialZoom}, range=${minZoom}-${maxZoom}, vector tiles available:`, hasVectorTiles);

        // Create map with dynamic configuration
        this.map = new maplibregl.Map({
            container: 'map',
            style: {
                version: 8,
                sources: {
                    'vector-tiles': {
                        type: 'vector',
                        tiles: [window.location.origin + '/api/v1/tiles/vector/usa/{z}/{x}/{y}.pbf']
                    },
                    'elevation-tiles': {
                        type: 'raster',
                        tiles: [this.getElevationTileURL()]
                    },
                },
                layers: [
                    // Background
                    {
                        id: 'background',
                        type: 'background',
                        paint: { 'background-color': '#f8f9fa' }
                    },
                    // Water bodies (only add if vector tiles available)
                    ...(hasVectorTiles ? [{
                        id: 'water',
                        type: 'fill',
                        source: 'vector-tiles',
                        'source-layer': 'water',
                        paint: { 'fill-color': '#3b82f6', 'fill-opacity': 0.6 }
                    }] : []),
                    // Roads (only add if vector tiles available)
                    ...(hasVectorTiles ? [{
                        id: 'roads',
                        type: 'line',
                        source: 'vector-tiles',
                        'source-layer': 'transportation',
                        paint: { 'line-color': '#6b7280', 'line-width': 1 }
                    }] : []),
                    // Contextual flood risk elevation overlay
                    {
                        id: 'elevation',
                        type: 'raster',
                        source: 'elevation-tiles',
                        paint: { 'raster-opacity': 0.6 }
                    }
                ]
            },
            center: [-89.5, 20], // Center of elevation coverage area (Florida/Gulf Coast)
            zoom: initialZoom,
            minZoom: minZoom,
            maxZoom: maxZoom
        });

        // Add navigation controls
        this.map.addControl(new maplibregl.NavigationControl(), 'top-right');

        // Add click handler for risk assessment
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
        
        waterLevelSlider.addEventListener('input', (e) => {
            this.currentWaterLevel = parseFloat(e.target.value);
            waterLevelDisplay.textContent = `${this.currentWaterLevel}m`;
            this.updateFloodLayer();
        });

        // Find location button
        document.getElementById('find-location').addEventListener('click', () => {
            this.findUserLocation();
        });

        // Initialize UI state
        this.updateViewMode();
    }

    getElevationTileURL() {
        if (this.viewMode === 'elevation') {
            return window.location.origin + '/api/tiles/topographical/{z}/{x}/{y}.png?v=' + Date.now();
        } else {
            return window.location.origin + '/api/tiles/elevation/' + this.currentWaterLevel + '/{z}/{x}/{y}.png?v=' + Date.now();
        }
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

    updateFloodLayer() {
        // Update elevation tiles based on current mode
        this.map.getSource('elevation-tiles').setTiles([this.getElevationTileURL()]);
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
}

// Initialize the map when the page loads
document.addEventListener('DOMContentLoaded', () => {
    new FloodMap();
});