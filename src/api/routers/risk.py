"""Risk assessment endpoints."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging

# Import elevation system
from elevation_loader import elevation_loader

router = APIRouter()
logger = logging.getLogger(__name__)

class LocationRequest(BaseModel):
    latitude: float
    longitude: float

class RiskResponse(BaseModel):
    latitude: float
    longitude: float
    elevation_m: Optional[float]
    flood_risk_level: str
    water_level_m: float
    risk_description: str

@router.post("/risk/location", response_model=RiskResponse)
async def assess_flood_risk(location: LocationRequest):
    """Assess flood risk for a specific location."""
    try:
        # Get actual elevation data - convert lat/lon to tile coordinates
        # Use a high zoom level for precise elevation lookup
        zoom = 14
        x, y = elevation_loader.deg2num(location.latitude, location.longitude, zoom)
        elevation_array = elevation_loader.get_elevation_for_tile(x, y, zoom)
        
        if elevation_array is not None:
            # Extract center pixel value as elevation for this point
            center_y, center_x = elevation_array.shape[0] // 2, elevation_array.shape[1] // 2
            elevation = float(elevation_array[center_y, center_x])
            if elevation == -32768:  # No-data value
                elevation = None
        else:
            elevation = None
        
        if elevation is None:
            logger.warning(f"No elevation data found for {location.latitude}, {location.longitude}")
            raise HTTPException(
                status_code=404, 
                detail=f"No elevation data available for coordinates {location.latitude}, {location.longitude}"
            )
        else:
            # Calculate flood risk based on elevation
            if elevation < 1.0:
                flood_risk_level = "very_high"
                risk_description = f"Very high flood risk - elevation {elevation:.1f}m is below typical flood levels"
            elif elevation < 3.0:
                flood_risk_level = "high" 
                risk_description = f"High flood risk - elevation {elevation:.1f}m is near flood-prone areas"
            elif elevation < 10.0:
                flood_risk_level = "moderate"
                risk_description = f"Moderate flood risk - elevation {elevation:.1f}m provides some protection"
            else:
                flood_risk_level = "low"
                risk_description = f"Low flood risk - elevation {elevation:.1f}m is well above typical flood levels"
        
        return RiskResponse(
            latitude=location.latitude,
            longitude=location.longitude,
            elevation_m=elevation,
            flood_risk_level=flood_risk_level,
            water_level_m=1.0,
            risk_description=risk_description
        )
        
    except Exception as e:
        logger.error(f"Error assessing flood risk: {e}")
        # Fallback to mock data on error
        return RiskResponse(
            latitude=location.latitude,
            longitude=location.longitude,
            elevation_m=None,
            flood_risk_level="unknown",
            water_level_m=1.0,
            risk_description="Error retrieving elevation data"
        )

@router.get("/risk/ip")
async def get_user_location_risk():
    """Get flood risk for user's current location (IP-based)."""
    # TODO: Implement IP geolocation + risk assessment
    # For now, return Tampa coordinates
    return RiskResponse(
        latitude=27.9506,
        longitude=-82.4572,
        elevation_m=12.2,
        flood_risk_level="low",
        water_level_m=1.0,
        risk_description="Low flood risk - above typical flood levels"
    )