import requests
import logging
import os
import colorsys
from dataclasses import dataclass
from math import floor
import math

from fasthtml.common import Div
from fasthtml.common import P
from fasthtml.common import fast_app
from fasthtml.common import Iframe
from fasthtml.common import FileResponse
from fasthtml.common import Response
from fasthtml.common import Titled
from fasthtml.common import Container
from fasthtml.common import Card
from fasthtml.common import H2
from fasthtml.common import Grid
from fasthtml.xtend import Favicon

import numpy as np
from diskcache import Cache
from dotenv import load_dotenv
from googlemaps import Client as GoogleMaps

import uvicorn
from rasterio.transform import rowcol

logging.basicConfig(
    format="%(filename)s:%(lineno)d - %(message)s",
    level=logging.INFO
)


load_dotenv()


# Initialize disk cache
cache = Cache("./cache")

app, rt = fast_app(
    hdrs=(Favicon(light_icon="./static/favicon.ico", dark_icon="./static/favicon.ico"))
)

DEBUG_COORDS = (27.95053694962414, -82.4585769277307)
DEBUG_IP = "23.111.165.2"
TILES_DIR = str(os.getenv("PROCESSED_DIR"))
# ALLOWED_ZOOM_LEVELS = [10, 11, 12, 13, 14, 15]
ALLOWED_ZOOM_LEVELS = [8, 9]
MAP_HEIGHT = "600px"


DEBUG_MODE = True

gmaps_api_key = os.environ.get("GMAP_API_KEY")
assert gmaps_api_key is not None, "GMAP_API_KEY is not set"

# Global variables to store the TIF data
tif_data: list = []
tif_bounds: list = []
tif_transform: list = []
tile_index = {}


@dataclass
class LocationInfo:
    city: str = "Unknown"
    region: str = "Unknown"
    country: str = "Unknown"
    latitude: float = 0.0
    longitude: float = 0.0


gmaps = GoogleMaps(key=gmaps_api_key)


def preload_tile_paths():
    tile_index = {}
    total_tiles = 0
    tif_counts = {}  # Track tiles per TIF directory

    logging.info(f"Checking for tiles directory: {TILES_DIR}")
    if not os.path.exists(TILES_DIR):
        logging.warning(f"Tiles directory not found: {TILES_DIR}")
        return tile_index

    logging.info(f"Loading tiles from: {TILES_DIR}")
    tif_dirs = os.listdir(TILES_DIR)
    logging.info(f"Found {len(tif_dirs)} TIF directories")

    for tif_dir in os.listdir(TILES_DIR):
        tif_path = os.path.join(TILES_DIR, tif_dir)
        if not os.path.isdir(tif_path):
            continue

        tif_counts[tif_dir] = 0  # Initialize counter for this TIF

        for z_dir in os.listdir(tif_path):
            if not z_dir.isdigit():
                continue
            z = int(z_dir)
            if z not in tile_index:
                tile_index[z] = {}

            z_path = os.path.join(tif_path, z_dir)
            for x_dir in os.listdir(z_path):
                if not x_dir.isdigit():
                    continue
                x = int(x_dir)
                if x not in tile_index[z]:
                    tile_index[z][x] = {}

                x_path = os.path.join(z_path, x_dir)
                for file in os.listdir(x_path):
                    if not file.endswith(".png"):
                        continue
                    y = int(file.replace(".png", ""))
                    tile_index[z][x][y] = tif_dir
                    total_tiles += 1
                    tif_counts[tif_dir] += 1
    logging.info(f"Loaded {total_tiles:,} tiles from {len(tif_counts)} TIF files")
    return tile_index


tile_index = preload_tile_paths()

def lat_lon_to_tile(lat, lon, zoom):
    n = 2.0**zoom
    xtile = floor((lon + 180.0) / 360.0 * n)
    ytile = floor((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    logging.info(
        f"Converting lat={lat}, lon={lon}, zoom={zoom} to tile: x={xtile}, y={ytile}"
    )
    return xtile, ytile


def tile_to_lat_lon(x, y, zoom):
    n = 2.0**zoom
    lon_deg = (x / n * 360.0) - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat_deg = math.degrees(lat_rad)
    return lat_deg, lon_deg


# Add this debug code to verify tile coverage:
z = ALLOWED_ZOOM_LEVELS[0]  # zoom level 8
for tif_dir in os.listdir(TILES_DIR):
    z_path = os.path.join(TILES_DIR, tif_dir, str(z))
    if not os.path.exists(z_path):
        continue
        
    x_dirs = [int(x) for x in os.listdir(z_path) if x.isdigit()]
    if not x_dirs:
        continue
        
    for x in x_dirs:
        y_files = [int(y.replace('.png', '')) for y in os.listdir(os.path.join(z_path, str(x))) if y.endswith('.png')]
        if y_files:
            logging.info(f"TIF {tif_dir} at z={z}, x={x}: y={min(y_files)}-{max(y_files)}")

def get_elevation_from_memory(latitude, longitude):
    # logging.info(f"Getting elevation for lat={latitude}, lon={longitude}")
    for i, bounds in enumerate(tif_bounds):
        if (
            bounds.left <= longitude <= bounds.right
            and bounds.bottom <= latitude <= bounds.top
        ):
            # Use rasterio's index function to get row, col
            row, col = rowcol(tif_transform[i], longitude, latitude)
            # logging.info(f"Calculated row={row}, col={col}")

            # Convert row and col to integers
            row, col = int(row), int(col)

            # Check if row and col are within bounds
            if 0 <= row < tif_data[i].shape[0] and 0 <= col < tif_data[i].shape[1]:
                elevation = tif_data[i][row, col]
                # logging.info(f"Elevation found: {elevation}")
                return float(elevation)
            else:
                logging.warning(
                    f"Calculated row or col out of bounds: row={row}, col={col}"
                )
                return None
    logging.warning(f"No matching bounds found for lat={latitude}, lon={longitude}")
    return None


def get_ip_geolocation(ip_address):
    api_key = os.environ.get("IP2LOC_API_KEY")
    url = f"https://api.ip2location.io/?key={api_key}&ip={ip_address}&format=json"

    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Error fetching IP geolocation: {e}")
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
            row_min, col_min = map(int, rowcol(tif_transform[i], min_lng, max_lat))
            row_max, col_max = map(int, rowcol(tif_transform[i], max_lng, min_lat))

            # Ensure we're within bounds
            row_min, row_max = max(0, row_min), min(tif_data[i].shape[0], row_max)
            col_min, col_max = max(0, col_min), min(tif_data[i].shape[1], col_max)

            # Extract the data subset
            data_subset = tif_data[i][row_min:row_max, col_min:col_max]

            # Log statistics about the data subset
            logging.info(
                f"Elevation data stats: min={np.nanmin(data_subset):.2f}, "
                f"max={np.nanmax(data_subset):.2f}, mean={np.nanmean(data_subset):.2f}, "
                f"median={np.nanmedian(data_subset):.2f}"
            )
            logging.info(f"Data shape: {data_subset.shape}")

            # Create lat/lon arrays for the subset
            lats = np.linspace(max_lat, min_lat, data_subset.shape[0])
            lons = np.linspace(min_lng, max_lng, data_subset.shape[1])
            lons, lats = np.meshgrid(lons, lats)

            # Flatten and combine the data
            result = list(zip(lats.flatten(), lons.flatten(), data_subset.flatten()))
            return [point for point in result if not np.isnan(point[2])]

    return []  # Return empty list if no matching TIF file found


def get_location_info(ip_address) -> LocationInfo:
    if DEBUG_MODE:
        return LocationInfo(
            "Tampa", "Florida", "United States", DEBUG_COORDS[0], DEBUG_COORDS[1]
        )

    cache_key = f"geo_{ip_address}"
    cached_result = cache.get(cache_key)
    if cached_result and isinstance(cached_result, tuple) and len(cached_result) == 5:
        return LocationInfo(
            city=str(cached_result[0]),
            region=str(cached_result[1]),
            country=str(cached_result[2]),
            latitude=cached_result[3],
            longitude=cached_result[4],
        )

    geolocation_data = get_ip_geolocation(ip_address)
    if geolocation_data:
        info = LocationInfo(
            city=geolocation_data.get("city_name", "Unknown"),
            region=geolocation_data.get("region_name", "Unknown"),
            country=geolocation_data.get("country_name", "Unknown"),
            latitude=float(geolocation_data.get("latitude", 0)),
            longitude=float(geolocation_data.get("longitude", 0)),
        )
        cache.set(
            cache_key,
            (info.city, info.region, info.country, info.latitude, info.longitude),
            expire=86400,
        )
        return info

    return LocationInfo()


def get_color(value):
    """Convert a value between -1 and 1 to an RGB color."""
    hue = (1 - (value + 1) / 2) * 240 / 360  # Map -1..1 to hue 240..0 (blue to red)
    rgb = colorsys.hsv_to_rgb(hue, 1, 1)
    return f"rgb({int(rgb[0]*255)}, {int(rgb[1]*255)}, {int(rgb[2]*255)})"


def generate_gmaps_html(latitude, longitude, elevation):
    tile_url_pattern = "/tiles/{z}/{x}/{y}"

    return f"""
    <div id="map" style="height: {MAP_HEIGHT}; width: 100%;"></div>
    <script src="https://maps.googleapis.com/maps/api/js?key={gmaps_api_key}"></script>
    <script>
        function initMap() {{
            const allowedZoomLevels = {ALLOWED_ZOOM_LEVELS};
            const initialZoom = allowedZoomLevels[Math.floor(allowedZoomLevels.length / 2)];

            const map = new google.maps.Map(document.getElementById("map"), {{
                center: {{ lat: {latitude}, lng: {longitude} }},
                zoom: initialZoom,
                mapTypeId: "terrain",
                zoomControl: true,
                scrollwheel: true,
                disableDoubleClickZoom: false,
                draggable: true,
                minZoom: Math.min(...allowedZoomLevels),
                maxZoom: Math.max(...allowedZoomLevels),
                restriction: {{
                    latLngBounds: {{
                        north: {latitude} + 0.1,
                        south: {latitude} - 0.1,
                        east: {longitude} + 0.1,
                        west: {longitude} - 0.1,
                    }},
                    strictBounds: false,
                }}
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

            const tileLayer = new google.maps.ImageMapType({{
                getTileUrl: function(coord, zoom) {{
                    if (allowedZoomLevels.includes(zoom)) {{
                        return '{tile_url_pattern}'
                            .replace('{{z}}', zoom)
                            .replace('{{x}}', coord.x)
                            .replace('{{y}}', coord.y);
                    }}
                    return "";
                }},
                tileSize: new google.maps.Size(256, 256),
                name: "Elevation Overlay",
                opacity: 0.6
            }});

            map.overlayMapTypes.insertAt(0, tileLayer);
        }}
    </script>
    <script>initMap();</script>
    """


def create_map(latitude, longitude):
    # cache_key = f"map_{latitude}_{longitude}"
    # cached_map = cache.get(cache_key)
    # if cached_map:
    #     logging.info(f"Cache hit for map: {cache_key}")
    #     return cached_map

    # logging.info(f"Cache miss for map: {cache_key}")
    elevation = get_elevation(latitude, longitude)
    map_html = generate_gmaps_html(latitude, longitude, elevation)
    # cache.set(cache_key, map_html, expire=86400)  # Cache for 24 hours
    return map_html


@app.get("/tiles/{z}/{x}/{y}")
def get_tile(z: int, x: int, y: int):
    if z not in ALLOWED_ZOOM_LEVELS:
        return Response(
            status_code=404,
            content=f"Only zoom levels {ALLOWED_ZOOM_LEVELS} are available",
        )

    # Fast lookup using nested dictionary
    if z in tile_index and x in tile_index[z] and y in tile_index[z][x]:
        tif_dir = tile_index[z][x][y]
        tile_path = os.path.join(TILES_DIR, tif_dir, str(z), str(x), f"{y}.png")
        return FileResponse(tile_path, media_type="image/png")

    return Response(status_code=404, content=f"Tile not found: z={z}, x={x}, y={y}")


@rt("/")
def get_root(request):
    logging.info("==== Running route / ====")

    if DEBUG_MODE:
        user_ip = DEBUG_IP
    else:
        user_ip = request.client.host if request.client else "Unknown"

    location = get_location_info(user_ip)
    elevation = get_elevation(location.latitude, location.longitude)

    latitude = location.latitude
    longitude = location.longitude
    city = location.city
    state = location.region
    country = location.country

    map_html = ""
    if latitude is not None and longitude is not None:
        map_html = generate_gmaps_html(latitude, longitude, elevation)
        x, y = lat_lon_to_tile(latitude, longitude, ALLOWED_ZOOM_LEVELS[0])

    if latitude is None:
        latitude = "Unknown"
    if longitude is None:
        longitude = "Unknown"
    if elevation is None:
        elevation = "Unknown"

    content = Titled(
        "Flood Buddy",
        Container(
            Card(
                H2("Location Information"),
                Grid(
                    Div(
                        P(f"IP Address: {user_ip}"),
                        P(f"City: {city}"),
                        P(f"State/Region: {state}"),
                        P(f"Country: {country}"),
                    ),
                    Div(
                        P(f"Latitude: {latitude}°"),
                        P(f"Longitude: {longitude}°"),
                        P(f"Elevation: {elevation} m"),
                    ),
                ),
            ),
            Card(H2("Map"), Iframe(srcdoc=map_html, width="100%", height=MAP_HEIGHT)),
        ),
    )
    return content

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5001,
        reload=False,
        log_config=None,
    )