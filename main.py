from fasthtml.common import Div, H1, P, fast_app, serve
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

app, rt = fast_app()

DEBUG_COORDS = (27.95053694962414, -82.4585769277307)


def get_location_info(latitude, longitude):
    geolocator = Nominatim(user_agent="my_app")
    try:
        location = geolocator.reverse(f"{latitude}, {longitude}")
        if location:
            address = location.raw["address"]
            city = address.get("city", "")
            state = address.get("state", "")
            country = address.get("country", "")
            return city, state, country
    except GeocoderTimedOut:
        pass
    return "Unknown", "Unknown", "Unknown"

@rt('/')
def get():
    # Get location information
    city, state, country = get_location_info(DEBUG_COORDS[0], DEBUG_COORDS[1])
    
    # Display coordinates and location info
    coordinates = Div(
        H1("User Location"),
        P(f"Latitude: {DEBUG_COORDS[0]}° N"),
        P(f"Longitude: {DEBUG_COORDS[1]}° W"),
        P(f"City: {city}"),
        P(f"State: {state}"),
        P(f"Country: {country}")
    )
    return coordinates

serve()