/**
 * Clean MapLibre implementation for flood risk mapping
 * No framework dependencies - pure JavaScript
 */

class FloodMap {
    constructor() {
        this.map = null;
        this.currentWaterLevel = 1.0;
        this.init();
    }

    init() {
        this.initializeMap();
        this.setupEventListeners();
        this.loadUserLocation();
    }

    initializeMap() {
        // Create map with clean configuration
        this.map = new maplibregl.Map({
            container: 'map',
            style: {
                version: 8,
                sources: {
                    'vector-tiles': {
                        type: 'vector',
                        tiles: [window.location.origin + '/api/tiles/vector/{z}/{x}/{y}.pbf']
                    },
                    'elevation-tiles': {
                        type: 'raster',
                        tiles: [window.location.origin + '/api/tiles/elevation/{z}/{x}/{y}.png']
                    },
                    'flood-tiles': {
                        type: 'raster',
                        tiles: [window.location.origin + '/api/tiles/flood/' + this.currentWaterLevel + '/{z}/{x}/{y}.png']
                    }
                },
                layers: [
                    // Background
                    {
                        id: 'background',
                        type: 'background',
                        paint: { 'background-color': '#f8f9fa' }
                    },
                    // Water bodies
                    {
                        id: 'water',
                        type: 'fill',
                        source: 'vector-tiles',
                        'source-layer': 'water',
                        paint: { 'fill-color': '#3b82f6', 'fill-opacity': 0.6 }
                    },
                    // Roads
                    {
                        id: 'roads',
                        type: 'line',
                        source: 'vector-tiles',
                        'source-layer': 'transportation',
                        paint: { 'line-color': '#6b7280', 'line-width': 1 }
                    },
                    // Elevation overlay
                    {
                        id: 'elevation',
                        type: 'raster',
                        source: 'elevation-tiles',
                        paint: { 'raster-opacity': 0.3 }
                    },
                    // Flood risk overlay
                    {
                        id: 'flood-risk',
                        type: 'raster',
                        source: 'flood-tiles',
                        paint: { 'raster-opacity': 0.7 }
                    }
                ]
            },
            center: [-82.4572, 27.9506], // Tampa
            zoom: 11,
            minZoom: 8,
            maxZoom: 16
        });

        // Add navigation controls
        this.map.addControl(new maplibregl.NavigationControl(), 'top-right');

        // Add click handler for risk assessment
        this.map.on('click', (e) => {
            this.assessLocationRisk(e.lngLat.lat, e.lngLat.lng);
        });
    }

    setupEventListeners() {
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
    }

    updateFloodLayer() {
        // Update flood tiles source with new water level
        this.map.getSource('flood-tiles').setTiles([
            window.location.origin + '/api/tiles/flood/' + this.currentWaterLevel + '/{z}/{x}/{y}.png'
        ]);
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
                    this.map.setZoom(12);
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