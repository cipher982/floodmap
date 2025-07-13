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
import rasterio
from rasterio.transform import rowcol

import sqlite3
import asyncio
import time
from collections import defaultdict
from fastapi import Request, HTTPException, Path
import queue
from io import BytesIO
from PIL import Image

# Prometheus metrics
from prometheus_client import Counter, Summary, make_asgi_app

# Optional Redis for distributed rate limiting
try:
    import redis.asyncio as aioredis  # type: ignore
except ImportError:  # pragma: no cover
    aioredis = None

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
ALLOWED_ZOOM_LEVELS = [10, 11, 12]
MAP_HEIGHT = "600px"


DEBUG_MODE = True

gmaps_api_key = os.environ.get("GMAP_API_KEY", "DISABLED_FOR_LOCAL_DEV")
# assert gmaps_api_key is not None, "GMAP_API_KEY is not set"  # DISABLED to prevent API quota usage

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


# gmaps = GoogleMaps(key=gmaps_api_key)  # DISABLED to prevent API quota usage


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


def load_elevation_data():
    """Load TIF elevation data into memory for flood calculations."""
    global tif_data, tif_bounds, tif_transform
    
    # Clear existing data
    tif_data.clear()
    tif_bounds.clear() 
    tif_transform.clear()
    
    # Check for input directory with TIF files
    input_dir = os.getenv("INPUT_DIR", "scratch/data_tampa")
    if not os.path.exists(input_dir):
        logging.warning(f"Input directory not found: {input_dir}")
        return
        
    # Find all TIF files
    tif_files = []
    for file in os.listdir(input_dir):
        if file.endswith('.tif'):
            tif_files.append(os.path.join(input_dir, file))
    
    if not tif_files:
        logging.warning(f"No TIF files found in {input_dir}")
        return
        
    logging.info(f"Loading {len(tif_files)} TIF files into memory...")
    
    for tif_file in tif_files:
        try:
            with rasterio.open(tif_file) as src:
                # Read elevation data
                data = src.read(1)  # Read first band
                bounds = src.bounds
                transform = src.transform
                
                # Store in global arrays
                tif_data.append(data)
                tif_bounds.append(bounds)
                tif_transform.append(transform)
                
                logging.info(f"Loaded {tif_file}: {data.shape} pixels, bounds={bounds}")
                
        except Exception as e:
            logging.error(f"Failed to load {tif_file}: {e}")
    
    logging.info(f"Successfully loaded {len(tif_data)} TIF files into memory")


# MBTiles path (preferred)
MBTILES_PATH = os.getenv("MBTILES_PATH", os.path.join(TILES_DIR, "elevation.mbtiles"))

# Simple connection pool for read-only MBTiles connections
_pool_size = int(os.getenv("MBTILES_POOL_SIZE", "4"))
_mbtiles_pool: queue.Queue[sqlite3.Connection] | None = None

if os.path.exists(MBTILES_PATH):
    _mbtiles_pool = queue.Queue(maxsize=_pool_size)
    try:
        for _ in range(_pool_size):
            conn = sqlite3.connect(
                f"file:{MBTILES_PATH}?mode=ro", uri=True, check_same_thread=False
            )
            conn.execute("PRAGMA journal_mode=OFF")
            conn.execute("PRAGMA synchronous=OFF")
            _mbtiles_pool.put(conn)
    except Exception as e:
        logging.error(f"Failed to initialize MBTiles pool: {e}")
        _mbtiles_pool = None

# Only preload directory index if MBTiles pool not present
if not _mbtiles_pool:
    tile_index = preload_tile_paths()
else:
    tile_index = {}

# Load elevation data into memory for flood calculations
load_elevation_data()

# Mount Prometheus ASGI app once and define metrics
try:
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    # Prometheus metric objects - only create if not already created
    REQUEST_TIME = Summary(
        "request_processing_seconds",
        "Time spent processing request",
        ["endpoint"],
    )
    TILE_HIT_COUNTER = Counter("tiles_served_total", "Total tiles served", ["source"])
    RATE_LIMIT_COUNTER = Counter(
        "rate_limit_exceeded_total", "Number of requests rejected by rate limiter"
    )
    MAP_RENDER_COUNTER = Counter("map_render_total", "Number of map pages rendered")
    FLOOD_TILE_COUNTER = Counter("flood_tiles_generated_total", "Flood overlay tiles generated")
    FLOOD_TILE_ERROR_COUNTER = Counter("flood_tile_errors_total", "Errors during flood tile generation")
except ValueError as e:
    if "Duplicated timeseries" in str(e):
        logging.warning("Prometheus metrics already registered, continuing...")
        # Create dummy metrics to avoid NameError
        class DummyMetric:
            def inc(self): pass
            def observe(self, val): pass
            def labels(self, *args): return self
        REQUEST_TIME = DummyMetric()
        TILE_HIT_COUNTER = DummyMetric()
        RATE_LIMIT_COUNTER = DummyMetric()
        MAP_RENDER_COUNTER = DummyMetric()
        FLOOD_TILE_COUNTER = DummyMetric()
        FLOOD_TILE_ERROR_COUNTER = DummyMetric()
    else:
        raise

# Redis client for distributed rate limiting
REDIS_URL = os.getenv("REDIS_URL")
redis_client = None
if REDIS_URL and aioredis is not None:
    try:
        redis_client = aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=False)
    except Exception as e:
        logging.error(f"Failed to connect to Redis at {REDIS_URL}: {e}")

# Fallback in-memory store
_tile_rate_state: defaultdict[str, list[float]] = defaultdict(list)

# Rate limiting configuration
MAX_TILES_PER_SECOND = int(os.getenv("MAX_TILES_PER_SECOND", "30"))


async def _rate_limit(client_ip: str):
    """Sliding-window rate limit per IP, backed by Redis if available."""
    if redis_client:
        key = f"rl:{client_ip}"
        try:
            pipe = redis_client.pipeline()
            pipe.incr(key)
            pipe.expire(key, 1)
            count, _ = await pipe.execute()
            if int(count) > MAX_TILES_PER_SECOND:
                RATE_LIMIT_COUNTER.inc()
                raise HTTPException(status_code=429, detail="Too many tile requests")
            return
        except Exception as e:
            logging.error(f"Redis rate-limit error: {e}")

    # Local in-memory fallback
    now = time.time()
    window = _tile_rate_state[client_ip]
    while window and now - window[0] > 1:
        window.pop(0)
    if len(window) >= MAX_TILES_PER_SECOND:
        RATE_LIMIT_COUNTER.inc()
        raise HTTPException(status_code=429, detail="Too many tile requests")
    window.append(now)


async def _async_fetch_mbtiles(z: int, x: int, y: int):
    """Fetch PNG bytes from MBTiles in a thread pool."""
    if not _mbtiles_pool:
        return None

    def _query():
        conn = None
        try:
            conn = _mbtiles_pool.get(timeout=5)
            cur = conn.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (z, x, y),
            )
            row = cur.fetchone()
            return row[0] if row else None
        except Exception as e:
            logging.error(f"MBTiles query error: {e}")
            return None
        finally:
            if conn:
                _mbtiles_pool.put(conn)

    return await asyncio.to_thread(_query)


def lat_lon_to_tile(lat, lon, zoom):
    n = 2.0**zoom
    xtile = int(floor((lon + 180.0) / 360.0 * n))
    ytile = int(floor((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n))
    return xtile, ytile


def tile_to_lat_lon(x, y, zoom):
    n = 2.0**zoom
    lon_deg = (x / n * 360.0) - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat_deg = math.degrees(lat_rad)
    return lat_deg, lon_deg


# Add this debug code to verify tile coverage (only run if not testing):
if __name__ == "__main__" and os.path.exists(TILES_DIR):
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


def generate_gmaps_html(latitude, longitude, elevation, water_level):
    error_tile = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/YoZ7xQAAAAASUVORK5CYII="
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

            // Elevation tiles
            const tileLayer = new google.maps.ImageMapType({{
                getTileUrl: function(coord, zoom) {{
                    if (allowedZoomLevels.includes(zoom)) {{
                        return '{tile_url_pattern}'
                            .replace('{{z}}', zoom)
                            .replace('{{x}}', coord.x)
                            .replace('{{y}}', coord.y);
                    }}
                    return "{error_tile}";
                }},
                tileSize: new google.maps.Size(256, 256),
                name: "Elevation Overlay",
                opacity: 0.6
            }});

            // Flood overlay tiles (semi-transparent)
            const floodLayer = new google.maps.ImageMapType({{
                getTileUrl: function(coord, zoom) {{
                    if (allowedZoomLevels.includes(zoom)) {{
                        return `/flood_tiles/{water_level}/` + zoom + '/' + coord.x + '/' + coord.y;
                    }}
                    return "";
                }},
                tileSize: new google.maps.Size(256, 256),
                name: "Flood Overlay",
                opacity: 0.5
            }});

            map.overlayMapTypes.insertAt(0, floodLayer);
            map.overlayMapTypes.insertAt(0, tileLayer);
        }}
    </script>
    <script>initMap();</script>
    """


def create_map(latitude, longitude, water_level):
    # cache_key = f"map_{latitude}_{longitude}"
    # cached_map = cache.get(cache_key)
    # if cached_map:
    #     logging.info(f"Cache hit for map: {cache_key}")
    #     return cached_map

    # logging.info(f"Cache miss for map: {cache_key}")
    elevation = get_elevation(latitude, longitude)
    map_html = generate_gmaps_html(latitude, longitude, elevation, water_level)
    # cache.set(cache_key, map_html, expire=86400)  # Cache for 24 hours
    return map_html


@app.get("/tiles/{z}/{x}/{y}")
async def get_tile(request: Request, z: int, x: int, y: int):
    # Basic zoom validation
    if z not in ALLOWED_ZOOM_LEVELS:
        raise HTTPException(status_code=404, detail="Zoom level not available")

    client_ip = request.client.host if request.client else "unknown"

    start_time = time.time()

    await _rate_limit(client_ip)

    # Try MBTiles first
    blob = await _async_fetch_mbtiles(z, x, y)
    if blob:
        TILE_HIT_COUNTER.labels("mbtiles").inc()
        REQUEST_TIME.labels("/tiles").observe(time.time() - start_time)
        return Response(
            content=blob,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
            },
        )

    # Fallback to file system tiles if present (TIF directory structure)
    if z in tile_index and x in tile_index[z] and y in tile_index[z][x]:
        tif_dir = tile_index[z][x][y]
        tile_path = os.path.join(TILES_DIR, tif_dir, str(z), str(x), f"{y}.png")
        if os.path.exists(tile_path):
            TILE_HIT_COUNTER.labels("disk").inc()
            REQUEST_TIME.labels("/tiles").observe(time.time() - start_time)
            return Response(
                content=open(tile_path, "rb").read(),
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=31536000, immutable"},
            )

    # Fallback to direct tile structure (z/x/y.png)
    direct_tile_path = os.path.join(TILES_DIR, str(z), str(x), f"{y}.png")
    if os.path.exists(direct_tile_path):
        TILE_HIT_COUNTER.labels("disk").inc()
        REQUEST_TIME.labels("/tiles").observe(time.time() - start_time)
        return Response(
            content=open(direct_tile_path, "rb").read(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    REQUEST_TIME.labels("/tiles").observe(time.time() - start_time)
    raise HTTPException(status_code=404, detail="Tile not found")


@rt("/")
def get_root(request, water_level: float = 1.0):
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
        map_html = generate_gmaps_html(latitude, longitude, elevation, water_level)
        x, y = lat_lon_to_tile(latitude, longitude, ALLOWED_ZOOM_LEVELS[0])

    if latitude is None:
        latitude = "Unknown"
    if longitude is None:
        longitude = "Unknown"
    if elevation is None:
        elevation = "Unknown"

    MAP_RENDER_COUNTER.inc()

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

# ---------------------------------------------------------------------------
# Health check endpoint
# ---------------------------------------------------------------------------


@app.get("/healthz")
async def healthz():
    status = {
        "status": "ok",
        "mbtiles": bool(_mbtiles_pool),
        "redis": bool(redis_client),
    }
    return status

# ---------------------------------------------------------------------------
# Flood simulation helpers
# ---------------------------------------------------------------------------


def _get_tile_bounds(z: int, x: int, y: int):
    """Return (lat_max, lat_min, lon_min, lon_max) for an XYZ tile."""
    lat_max, lon_min = tile_to_lat_lon(x, y, z)
    lat_min, lon_max = tile_to_lat_lon(x + 1, y + 1, z)
    return lat_max, lat_min, lon_min, lon_max


def _generate_flood_overlay_png(level_m: float, z: int, x: int, y: int) -> bytes | None:
    """Return a PNG byte string with semi-transparent blue where elevation <= level."""
    lat_max, lat_min, lon_min, lon_max = _get_tile_bounds(z, x, y)

    # Sample 64×64 grid for speed then upscale to 256.
    rows, cols = 64, 64
    lats = np.linspace(lat_max, lat_min, rows)
    lons = np.linspace(lon_min, lon_max, cols)
    mask = np.zeros((rows, cols), dtype=bool)

    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            elev = get_elevation_from_memory(lat, lon)
            if elev is not None and elev <= level_m:
                mask[i, j] = True

    if not mask.any():
        return None  # No flooded pixels in this tile

    # Upscale mask to 256×256  
    mask_img = Image.fromarray(mask.astype("uint8") * 255).resize((256, 256), Image.NEAREST)
    rgba = Image.new("RGBA", (256, 256), (0, 0, 255, 0))  # transparent
    blue = Image.new("RGBA", (256, 256), (0, 0, 255, 120))
    rgba.paste(blue, mask=mask_img)

    buf = BytesIO()
    rgba.save(buf, format="PNG")
    return buf.getvalue()

# ---------------------------------------------------------------------------
# Flood simulation endpoints
# ---------------------------------------------------------------------------


@app.get("/risk/{water_level_m}")
async def risk_endpoint(
    request: Request,
    water_level_m: float = Path(
        ..., description="Water level in meters", ge=0, le=100, title="water_level_m"
    ),
):
    """Return risk assessment at client's location (DEBUG uses fixed coords)."""
    if DEBUG_MODE:
        lat, lon = DEBUG_COORDS
    else:
        user_ip = request.client.host if request.client else "unknown"
        loc = get_location_info(user_ip)
        lat, lon = loc.latitude, loc.longitude

    elev = get_elevation(lat, lon)

    if elev is None:
        raise HTTPException(
            status_code=404,
            detail="Elevation data not available for the requested location",
        )

    status = "risk" if elev <= water_level_m else "safe"
    return {
        "latitude": lat,
        "longitude": lon,
        "elevation_m": elev,
        "water_level_m": water_level_m,
        "status": status,
    }


@app.get("/flood_tiles/{level}/{z}/{x}/{y}")
async def flood_tile(
    level: float = Path(..., ge=0, le=100, description="Water level in meters"),
    z: int = Path(..., ge=min(ALLOWED_ZOOM_LEVELS), le=max(ALLOWED_ZOOM_LEVELS)),
    x: int = Path(..., description="Tile X coordinate"),
    y: int = Path(..., description="Tile Y coordinate"),
):
    """Return a semi-transparent overlay tile representing flooded area."""
    # Validate tile coordinate bounds for given zoom
    max_index = (1 << z) - 1
    if not (0 <= x <= max_index and 0 <= y <= max_index):
        raise HTTPException(status_code=400, detail="Tile indices out of range for zoom level")

    try:
        png_bytes = await asyncio.to_thread(_generate_flood_overlay_png, level, z, x, y)
    except Exception as exc:
        logging.exception("Flood overlay generation failed", extra={"z": z, "x": x, "y": y})
        FLOOD_TILE_ERROR_COUNTER.inc()
        png_bytes = None

    if png_bytes is None:
        # No flooded pixels or outside DEM coverage
        raise HTTPException(
            status_code=204,
            detail="No flooded area in this tile for the specified water level",
        )

    FLOOD_TILE_COUNTER.inc()
    return Response(content=png_bytes, media_type="image/png", headers={"Cache-Control": "public, max-age=300"})

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5001,
        reload=False,
        log_config=None,
    )