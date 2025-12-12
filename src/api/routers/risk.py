"""Risk assessment endpoints."""

import logging
import math

# Import elevation system
from elevation_loader import elevation_loader
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter()
logger = logging.getLogger(__name__)


class LocationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    latitude: float
    longitude: float
    water_level_m: float = Field(1.0, alias="waterLevelM")


class RiskResponse(BaseModel):
    latitude: float
    longitude: float
    elevation_m: float | None
    flood_risk_level: str
    water_level_m: float
    risk_description: str


@router.post("/risk/location", response_model=RiskResponse)
async def assess_flood_risk(location: LocationRequest):
    """Assess flood risk for a specific location."""
    try:
        # IMPORTANT: frontend tile availability is capped at z=11 to match precompressed coverage.
        # Keep risk sampling within that range so we don't depend on runtime generation.
        zoom = 11

        # Compute both the tile indices and the within-tile pixel, so we sample the
        # requested point (not just the tile center).
        lat_rad = math.radians(location.latitude)
        n = 2.0**zoom
        x_float = (location.longitude + 180.0) / 360.0 * n
        y_float = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
        x_tile = int(x_float)
        y_tile = int(y_float)
        px = int((x_float - x_tile) * 256)
        py = int((y_float - y_tile) * 256)
        # Clamp to tile bounds (float math near edges can produce 256)
        px = min(255, max(0, px))
        py = min(255, max(0, py))

        elevation_array = elevation_loader.get_elevation_for_tile(x_tile, y_tile, zoom)

        if elevation_array is not None:
            elevation = float(elevation_array[py, px])
            if elevation == -32768:  # No-data value (see config.NODATA_VALUE default)
                elevation = None
        else:
            elevation = None

        if elevation is None:
            logger.warning(
                f"No elevation data found for {location.latitude}, {location.longitude}"
            )
            raise HTTPException(
                status_code=404,
                detail=f"No elevation data available for coordinates {location.latitude}, {location.longitude}",
            )
        else:
            # Calculate flood risk based on elevation relative to water level.
            relative = elevation - float(location.water_level_m)
            if relative < 0.5:
                flood_risk_level = "very_high"
                risk_description = (
                    f"Very high flood risk - {relative:.1f}m above water level"
                )
            elif relative < 2.0:
                flood_risk_level = "high"
                risk_description = (
                    f"High flood risk - {relative:.1f}m above water level"
                )
            elif relative < 5.0:
                flood_risk_level = "moderate"
                risk_description = (
                    f"Moderate flood risk - {relative:.1f}m above water level"
                )
            else:
                flood_risk_level = "low"
                risk_description = f"Low flood risk - {relative:.1f}m above water level"

        return RiskResponse(
            latitude=location.latitude,
            longitude=location.longitude,
            elevation_m=elevation,
            flood_risk_level=flood_risk_level,
            water_level_m=float(location.water_level_m),
            risk_description=f"{risk_description} (z{zoom} sample)",
        )

    except Exception as e:
        logger.error(f"Error assessing flood risk: {e}")
        # Fallback to mock data on error
        return RiskResponse(
            latitude=location.latitude,
            longitude=location.longitude,
            elevation_m=None,
            flood_risk_level="unknown",
            water_level_m=float(location.water_level_m),
            risk_description="Error retrieving elevation data",
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
        risk_description="Low flood risk - above typical flood levels",
    )
