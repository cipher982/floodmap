import logging

from fasthtml.common import Div, H1, P, fast_app, serve, Iframe
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import folium
from diskcache import Cache

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize disk cache
cache = Cache("./cache")

app, rt = fast_app()

DEBUG_COORDS = (27.95053694962414, -82.4585769277307)
DEBUG_MODE = True


def get_location_info(latitude, longitude):
    if DEBUG_MODE:
        return "Tampa", "Florida", "United States"

    cache_key = f"geo_{latitude}_{longitude}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return cached_result

    geolocator = Nominatim(user_agent="my_app")
    try:
        location = geolocator.reverse(f"{latitude}, {longitude}")
        if location:
            address = location.raw["address"]
            city = address.get("city", "")
            state = address.get("state", "")
            country = address.get("country", "")
            result = (city, state, country)
            cache.set(cache_key, result, expire=86400)  # Cache for 24 hours
            return result
    except GeocoderTimedOut:
        pass
    return "Unknown", "Unknown", "Unknown"


def create_map(latitude, longitude):
    cache_key = f"map_{latitude}_{longitude}"
    cached_map = cache.get(cache_key)
    if cached_map:
        logger.info(f"Cache hit for map: {cache_key}")
        return cached_map

    logger.info(f"Cache miss for map: {cache_key}")
    m = folium.Map(location=[latitude, longitude], zoom_start=13)
    folium.Marker([latitude, longitude]).add_to(m)
    map_html = m.get_root().render()
    cache.set(cache_key, map_html, expire=86400)  # Cache for 24 hours
    return map_html

@rt('/')
def get():
    # Get location information
    city, state, country = get_location_info(DEBUG_COORDS[0], DEBUG_COORDS[1])
    
    # Create map
    map_html = create_map(DEBUG_COORDS[0], DEBUG_COORDS[1])
    
    # Display coordinates, location info, and map
    content = Div(
        H1("User Location"),
        P(f"Latitude: {DEBUG_COORDS[0]}° N"),
        P(f"Longitude: {DEBUG_COORDS[1]}° W"),
        P(f"City: {city}"),
        P(f"State: {state}"),
        P(f"Country: {country}"),
        Iframe(srcdoc=map_html, width="100%", height="400px")
    )
    return content

serve()