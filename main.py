import requests
import logging
import os
import json
import colorsys

from fasthtml.common import Div, H1, P, fast_app, serve, Iframe
from fasthtml.xtend import Favicon

import numpy as np
from diskcache import Cache
from dotenv import load_dotenv
from googlemaps import Client as GoogleMaps

import rasterio


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

# Global variables to store the TIF data
tif_data = None
tif_bounds = None
tif_transform = None


gmaps = GoogleMaps(key=gmaps_api_key)


def load_tif_data():
    global tif_data, tif_bounds, tif_transform
    data_dir = "./data"

    tif_data = []
    tif_bounds = []
    tif_transform = []

    for filename in os.listdir(data_dir):
        if filename.endswith("_v3.tif"):
            tif_path = os.path.join(data_dir, filename)
            with rasterio.open(tif_path) as src:
                data = src.read(1)
                bounds = src.bounds
                tif_data.append(data)
                tif_bounds.append(bounds)
                tif_transform.append(src.transform)
                logger.info(f"Loaded {filename}: shape={data.shape}, bounds={bounds}")

    logger.info(f"Loaded {len(tif_data)} TIF files")


logger.info("Loading TIF data...")
load_tif_data()
logger.info("TIF data loaded")


def get_elevation_from_memory(latitude, longitude):
    # logger.info(f"Getting elevation for lat={latitude}, lon={longitude}")
    for i, bounds in enumerate(tif_bounds):
        if (
            bounds.left <= longitude <= bounds.right
            and bounds.bottom <= latitude <= bounds.top
        ):
            # Use rasterio's index function to get row, col
            row, col = rasterio.transform.rowcol(tif_transform[i], longitude, latitude)
            # logger.info(f"Calculated row={row}, col={col}")

            # Convert row and col to integers
            row, col = int(row), int(col)

            # Check if row and col are within bounds
            if 0 <= row < tif_data[i].shape[0] and 0 <= col < tif_data[i].shape[1]:
                elevation = tif_data[i][row, col]
                # logger.info(f"Elevation found: {elevation}")
                return float(elevation)
            else:
                logger.warning(
                    f"Calculated row or col out of bounds: row={row}, col={col}"
                )
                return None
    logger.warning(f"No matching bounds found for lat={latitude}, lon={longitude}")
    return None


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


# Update the get_elevation function
def get_elevation(latitude, longitude):
    cache_key = f"elevation_{latitude}_{longitude}"
    cached_elevation = cache.get(cache_key)
    if cached_elevation:
        return cached_elevation

    elevation = get_elevation_from_memory(latitude, longitude)
    if elevation is not None:
        cache.set(cache_key, elevation, expire=86400)  # Cache for 24 hours
    return elevation


def get_elevation_data(center_lat, center_lng, radius=0.05):
    """Get elevation data for a region around the center coordinates."""
    for i, bounds in enumerate(tif_bounds):
        if (
            bounds.left <= center_lng <= bounds.right
            and bounds.bottom <= center_lat <= bounds.top
        ):
            # Calculate the region of interest
            min_lat, max_lat = center_lat - radius, center_lat + radius
            min_lng, max_lng = center_lng - radius, center_lng + radius

            # Convert lat/lon to row/col
            row_min, col_min = map(
                int, rasterio.transform.rowcol(tif_transform[i], min_lng, max_lat)
            )
            row_max, col_max = map(
                int, rasterio.transform.rowcol(tif_transform[i], max_lng, min_lat)
            )

            # Ensure we're within bounds
            row_min, row_max = max(0, row_min), min(tif_data[i].shape[0], row_max)
            col_min, col_max = max(0, col_min), min(tif_data[i].shape[1], col_max)

            # Extract the data subset
            data_subset = tif_data[i][row_min:row_max, col_min:col_max]

            # Log statistics about the data subset
            logger.info(
                f"Elevation data stats: min={np.nanmin(data_subset):.2f}, "
                f"max={np.nanmax(data_subset):.2f}, mean={np.nanmean(data_subset):.2f}, "
                f"median={np.nanmedian(data_subset):.2f}"
            )
            logger.info(f"Data shape: {data_subset.shape}")

            # Create lat/lon arrays for the subset
            lats = np.linspace(max_lat, min_lat, data_subset.shape[0])
            lons = np.linspace(min_lng, max_lng, data_subset.shape[1])
            lons, lats = np.meshgrid(lons, lats)

            # Flatten and combine the data
            result = list(zip(lats.flatten(), lons.flatten(), data_subset.flatten()))
            return [point for point in result if not np.isnan(point[2])]

    return []  # Return empty list if no matching TIF file found


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



def get_color(value):
    """Convert a value between -1 and 1 to an RGB color."""
    hue = (1 - (value + 1) / 2) * 240 / 360  # Map -1..1 to hue 240..0 (blue to red)
    rgb = colorsys.hsv_to_rgb(hue, 1, 1)
    return f"rgb({int(rgb[0]*255)}, {int(rgb[1]*255)}, {int(rgb[2]*255)})"



def generate_gmaps_html(latitude, longitude, elevation):
    elevation_data = get_elevation_data(latitude, longitude)
    
    if not elevation_data:
        return "<p>No elevation data available for this location.</p>"

    lats, lngs, elevs = zip(*elevation_data)
    min_elev, max_elev = np.min(elevs), np.max(elevs)
    mean_elev = np.mean(elevs)

    logger.info(f"Elevation data stats: min={min_elev:.2f}, max={max_elev:.2f}, "
                f"mean={mean_elev:.2f}, range={max_elev - min_elev:.2f}")
    logger.info(f"Data shape: {len(lats)}x{len(lngs)}")

    # Non-linear normalization
    normalized_elevs = np.clip((np.array(elevs) - mean_elev) / (max_elev - mean_elev), -1, 1)
    normalized_elevs = np.sign(normalized_elevs) * np.abs(normalized_elevs) ** 0.5

    # Reduce the number of points (e.g., take every 10th point)
    step = 10
    heatmap_data = [
        {
            "lat": float(lat),
            "lng": float(lng),
            "color": get_color(norm_elev)
        }
        for lat, lng, norm_elev in zip(lats[::step], lngs[::step], normalized_elevs[::step])
    ]

    logger.info(f"Generated {len(heatmap_data)} heatmap points")

    heatmap_data_json = json.dumps(heatmap_data)

    return f"""
    <div id="map" style="height: 400px; width: 100%;"></div>
    <script src="https://maps.googleapis.com/maps/api/js?key={gmaps_api_key}"></script>
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

            const heatmapData = {heatmap_data_json};
            
            heatmapData.forEach(point => {{
                new google.maps.Circle({{
                    strokeColor: point.color,
                    strokeOpacity: 0.8,
                    strokeWeight: 1,
                    fillColor: point.color,
                    fillOpacity: 0.35,
                    map,
                    center: {{ lat: point.lat, lng: point.lng }},
                    radius: 50,
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
