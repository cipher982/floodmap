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
                        tiles: [this.getElevationTileURL()]
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