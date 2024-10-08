import requests
import logging
import os


from fasthtml.common import Div, H1, P, fast_app, serve, Iframe
from fasthtml.xtend import Favicon

import numpy as np
from scipy.interpolate import griddata
import folium
from diskcache import Cache
from dotenv import load_dotenv
from googlemaps import Client as GoogleMaps


load_dotenv()


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize disk cache
cache = Cache("./cache")

app, rt = fast_app(
    hdrs=(Favicon(light_icon="./static/favicon.ico", dark_icon="./static/favicon.ico"))
)

DEBUG_COORDS = (27.95053694962414, -82.4585769277307)
DEBUG_IP = "23.111.165.2"

DEBUG_MODE = True

gmaps_api_key = os.environ.get("GMAP_API_KEY")
assert gmaps_api_key is not None, "GMAP_API_KEY is not set"


gmaps = GoogleMaps(key=gmaps_api_key)


def get_ip_geolocation(ip_address):
    api_key = os.environ.get("IP2LOC_API_KEY")
    url = f"https://api.ip2location.io/?key={api_key}&ip={ip_address}&format=json"

    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error fetching IP geolocation: {e}")
        return None


def get_elevation(latitude, longitude):
    cache_key = f"elevation_{latitude}_{longitude}"
    cached_elevation = cache.get(cache_key)
    if cached_elevation:
        return cached_elevation

    try:
        elevation_result = gmaps.elevation((latitude, longitude))
        if elevation_result:
            elevation = round(elevation_result[0]["elevation"], 2)
            cache.set(cache_key, elevation, expire=86400)  # Cache for 24 hours
            return elevation
    except Exception as e:
        logger.error(f"Error fetching elevation: {e}")

    return None


def get_elevation_data(center_lat, center_lng, radius=5000, samples=20):
    cache_key = f"elevation_data_{center_lat}_{center_lng}_{radius}_{samples}"
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data

    # Generate a grid of points
    lat_range = np.linspace(center_lat - 0.05, center_lat + 0.05, samples)
    lng_range = np.linspace(center_lng - 0.05, center_lng + 0.05, samples)
    grid_lat, grid_lng = np.meshgrid(lat_range, lng_range)

    points = [(lat, lng) for lat, lng in zip(grid_lat.flatten(), grid_lng.flatten())]

    # Get elevations for all points
    elevations = gmaps.elevation(points)
    result = [
        (p["location"]["lat"], p["location"]["lng"], p["elevation"]) for p in elevations
    ]

    cache.set(cache_key, result, expire=86400 * 7)  # Cache for a week
    return result


def get_location_info(ip_address):
    if DEBUG_MODE:
        return "Tampa", "Florida", "United States", DEBUG_COORDS[0], DEBUG_COORDS[1]

    cache_key = f"geo_{ip_address}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return cached_result

    geolocation_data = get_ip_geolocation(ip_address)
    if geolocation_data:
        city = geolocation_data.get("city_name", "Unknown")
        region = geolocation_data.get("region_name", "Unknown")
        country = geolocation_data.get("country_name", "Unknown")
        latitude = geolocation_data.get("latitude")
        longitude = geolocation_data.get("longitude")
        if latitude is not None and longitude is not None:
            result = (city, region, country, float(latitude), float(longitude))
            cache.set(cache_key, result, expire=86400)  # Cache for 24 hours
            return result
    return "Unknown", "Unknown", "Unknown", None, None


def generate_gmaps_html(latitude, longitude, elevation):
    elevation_data = get_elevation_data(latitude, longitude)

    # Prepare data for contour lines and heatmap
    lats, lngs, elevs = zip(*elevation_data)
    grid_lat = np.linspace(min(lats), max(lats), 100)
    grid_lng = np.linspace(min(lngs), max(lngs), 100)
    grid_lat, grid_lng = np.meshgrid(grid_lat, grid_lng)
    grid_elev = griddata((lats, lngs), elevs, (grid_lat, grid_lng), method="cubic")

    contour_levels = np.linspace(np.min(elevs), np.max(elevs), 10)

    # Convert grid data to a format suitable for Google Maps
    heatmap_data = [
        {"lat": lat, "lng": lng, "elevation": elev}
        for lat, lng, elev in zip(
            grid_lat.flatten(), grid_lng.flatten(), grid_elev.flatten()
        )
        if not np.isnan(elev)
    ]

    if DEBUG_MODE:
        elevations = [elev[2] for elev in elevation_data]
        logger.info(
            f"Elevation data - Min: {min(elevations)}, Max: {max(elevations)}, Mean: {np.mean(elevations)}, Std: {np.std(elevations)}"
        )

    return f"""
    <div id="map" style="height: 400px; width: 100%;"></div>
    <script src="https://maps.googleapis.com/maps/api/js?key={gmaps_api_key}&libraries=visualization"></script>
    <script src="https://cdn.jsdelivr.net/npm/@turf/turf@6/turf.min.js"></script>
    <script>
        function initMap() {{
            const map = new google.maps.Map(document.getElementById("map"), {{
                center: {{ lat: {latitude}, lng: {longitude} }},
                zoom: 13,
                mapTypeId: "terrain"
            }});

            const marker = new google.maps.Marker({{
                position: {{ lat: {latitude}, lng: {longitude} }},
                map: map,
                title: "Your location"
            }});

            const infowindow = new google.maps.InfoWindow({{
                content: "Lat: {latitude}, Lon: {longitude}<br>Elevation: {elevation} m"
            }});

            marker.addListener("click", () => {{
                infowindow.open(map, marker);
            }});

            // Add heatmap layer
            const heatmapData = {heatmap_data};
            const heatmap = new google.maps.visualization.HeatmapLayer({{
                data: heatmapData.map(point => ({{
                    location: new google.maps.LatLng(point.lat, point.lng),
                    weight: point.elevation
                }})),
                map: map,
                radius: 20,
                opacity: 0.7,
                gradient: [
                    "rgba(0, 255, 255, 0)",
                    "rgba(0, 255, 255, 1)",
                    "rgba(0, 191, 255, 1)",
                    "rgba(0, 127, 255, 1)",
                    "rgba(0, 63, 255, 1)",
                    "rgba(0, 0, 255, 1)",
                    "rgba(0, 0, 223, 1)",
                    "rgba(0, 0, 191, 1)",
                    "rgba(0, 0, 159, 1)",
                    "rgba(0, 0, 127, 1)",
                    "rgba(63, 0, 91, 1)",
                    "rgba(127, 0, 63, 1)",
                    "rgba(191, 0, 31, 1)",
                    "rgba(255, 0, 0, 1)"
                ]
            }});

            // Add contour lines
            const elevationData = {elevation_data};
            const contourLevels = {contour_levels.tolist()};
            
            const points = turf.points(elevationData.map(p => [p[1], p[0], p[2]]));
            const bbox = turf.bbox(points);
            const grid = turf.interpolate(points, 100, {{
                gridType: "point",
                property: "elevation",
                units: "kilometers"
            }});

            contourLevels.forEach(level => {{
                const contours = turf.isolines(grid, level, {{zProperty: "elevation"}});
                contours.features.forEach(feature => {{
                    const path = feature.geometry.coordinates[0].map(coord => ({{
                        lat: coord[1],
                        lng: coord[0]
                    }}));
                    
                    new google.maps.Polyline({{
                        path: path,
                        geodesic: true,
                        strokeColor: "#FF0000",
                        strokeOpacity: 0.5,
                        strokeWeight: 2,
                        map: map
                    }});
                }});
            }});
        }}
    </script>
    <script>initMap();</script>
    """


def create_map(latitude, longitude):
    # cache_key = f"map_{latitude}_{longitude}"
    # cached_map = cache.get(cache_key)
    # if cached_map:
    #     logger.info(f"Cache hit for map: {cache_key}")
    #     return cached_map

    # logger.info(f"Cache miss for map: {cache_key}")
    elevation = get_elevation(latitude, longitude)
    map_html = generate_gmaps_html(latitude, longitude, elevation)
    # cache.set(cache_key, map_html, expire=86400)  # Cache for 24 hours
    return map_html


@rt("/")
def get(request):
    logger.info("==== Running route / ====")

    if DEBUG_MODE:
        user_ip = DEBUG_IP
    else:
        user_ip = request.client.host if request.client else "Unknown"

    city, state, country, latitude, longitude = get_location_info(user_ip)

    # Create map
    map_html = ""
    if latitude is not None and longitude is not None:
        map_html = create_map(latitude, longitude)

    # Display coordinates, location info, and map
    content = Div(
        H1("User Location"),
        P(f"IP Address: {user_ip}"),
        P(f"City: {city}"),
        P(f"State/Region: {state}"),
        P(f"Country: {country}"),
        P(f"Latitude: {latitude}°") if latitude else P("Latitude: Unknown"),
        P(f"Longitude: {longitude}°") if longitude else P("Longitude: Unknown"),
        P(f"Elevation: {get_elevation(latitude, longitude)} m")
        if latitude and longitude
        else P("Elevation: Unknown"),
        Iframe(srcdoc=map_html, width="100%", height="400px")
        if map_html
        else P("Map not available"),
    )
    return content


serve()
