"""
Comprehensive error handling framework for FloodMap application.
Provides structured error responses, logging, and graceful degradation patterns.
"""

import logging
import traceback
import uuid
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, Union
from enum import Enum
import numpy as np

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class ErrorCode(Enum):
    """Standardized error codes for the application."""
    
    # Data integrity errors
    ELEVATION_DATA_CORRUPT = "ELEVATION_DATA_CORRUPT"
    ELEVATION_DATA_MISSING = "ELEVATION_DATA_MISSING"
    CACHE_DATA_INVALID = "CACHE_DATA_INVALID"
    
    # External service errors
    TILESERVER_UNAVAILABLE = "TILESERVER_UNAVAILABLE"
    TILESERVER_TIMEOUT = "TILESERVER_TIMEOUT"
    GEOLOCATION_SERVICE_FAILED = "GEOLOCATION_SERVICE_FAILED"
    REDIS_CONNECTION_FAILED = "REDIS_CONNECTION_FAILED"
    
    # Input validation errors
    INVALID_COORDINATES = "INVALID_COORDINATES"
    INVALID_TILE_COORDINATES = "INVALID_TILE_COORDINATES"
    INVALID_WATER_LEVEL = "INVALID_WATER_LEVEL"
    INVALID_IP_ADDRESS = "INVALID_IP_ADDRESS"
    
    # Resource errors
    TILE_NOT_FOUND = "TILE_NOT_FOUND"
    ELEVATION_NOT_AVAILABLE = "ELEVATION_NOT_AVAILABLE"
    MEMORY_LIMIT_EXCEEDED = "MEMORY_LIMIT_EXCEEDED"
    
    # Rate limiting errors
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    RATE_LIMITER_UNAVAILABLE = "RATE_LIMITER_UNAVAILABLE"
    
    # Authentication/Authorization errors
    API_KEY_INVALID = "API_KEY_INVALID"
    ACCESS_DENIED = "ACCESS_DENIED"
    
    # Internal errors
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


@dataclass
class ErrorDetails:
    """Structured error details for consistent error responses."""
    
    error_code: str
    message: str
    user_message: str  # User-friendly message
    details: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None
    request_id: Optional[str] = None
    suggestions: Optional[list] = None


class FloodMapError(Exception):
    """Base exception class for FloodMap-specific errors."""
    
    def __init__(
        self, 
        error_code: ErrorCode, 
        message: str, 
        user_message: str = None,
        details: Dict[str, Any] = None,
        suggestions: list = None,
        cause: Exception = None
    ):
        self.error_code = error_code
        self.message = message
        self.user_message = user_message or self._get_default_user_message(error_code)
        self.details = details or {}
        self.suggestions = suggestions or []
        self.cause = cause
        self.request_id = str(uuid.uuid4())
        from datetime import timezone
        self.timestamp = datetime.now(timezone.utc).isoformat()
        
        super().__init__(self.message)
    
    def _get_default_user_message(self, error_code: ErrorCode) -> str:
        """Get default user-friendly message for error codes."""
        messages = {
            ErrorCode.ELEVATION_DATA_MISSING: "Elevation data is not available for this location.",
            ErrorCode.TILE_NOT_FOUND: "Map data is not available for this area.",
            ErrorCode.TILESERVER_UNAVAILABLE: "Map service is temporarily unavailable.",
            ErrorCode.INVALID_COORDINATES: "The provided coordinates are not valid.",
            ErrorCode.RATE_LIMIT_EXCEEDED: "Too many requests. Please try again in a moment.",
            ErrorCode.GEOLOCATION_SERVICE_FAILED: "Could not determine your location.",
            ErrorCode.INTERNAL_SERVER_ERROR: "An internal error occurred. Please try again.",
        }
        return messages.get(error_code, "An error occurred while processing your request.")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for API responses."""
        return {
            "error": self.error_code.value,
            "message": self.message,
            "user_message": self.user_message,
            "details": self.details,
            "suggestions": self.suggestions,
            "timestamp": self.timestamp,
            "request_id": self.request_id
        }


class ElevationDataError(FloodMapError):
    """Errors related to elevation data processing."""
    pass


class TileServiceError(FloodMapError):
    """Errors related to tile serving."""
    pass


class ValidationError(FloodMapError):
    """Input validation errors."""
    pass


class ExternalServiceError(FloodMapError):
    """Errors from external services."""
    pass


class RateLimitError(FloodMapError):
    """Rate limiting errors."""
    pass


class ErrorHandler:
    """Centralized error handling and logging."""
    
    def __init__(self, logger: logging.Logger = None):
        self.logger = logger or logging.getLogger(__name__)
    
    def log_error(
        self, 
        error: Union[FloodMapError, Exception], 
        request: Request = None,
        extra_context: Dict[str, Any] = None
    ) -> None:
        """Log error with structured context."""
        
        context = {
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
        
        if isinstance(error, FloodMapError):
            context.update({
                "error_code": error.error_code.value,
                "request_id": error.request_id,
                "user_message": error.user_message,
                "details": error.details
            })
        
        if request:
            context.update({
                "method": request.method,
                "url": str(request.url),
                "user_agent": request.headers.get("user-agent"),
                "client_ip": request.client.host if request.client else "unknown"
            })
        
        if extra_context:
            context.update(extra_context)
        
        # Log with appropriate level
        if isinstance(error, FloodMapError):
            if error.error_code in [ErrorCode.INTERNAL_SERVER_ERROR, ErrorCode.ELEVATION_DATA_CORRUPT]:
                self.logger.error("FloodMap Error", extra=context, exc_info=error.cause)
            else:
                self.logger.warning("FloodMap Error", extra=context)
        else:
            self.logger.error("Unhandled Error", extra=context, exc_info=True)
    
    def create_http_exception(self, error: FloodMapError) -> HTTPException:
        """Convert FloodMapError to HTTPException."""
        
        status_code_map = {
            ErrorCode.INVALID_COORDINATES: 400,
            ErrorCode.INVALID_TILE_COORDINATES: 400,
            ErrorCode.INVALID_WATER_LEVEL: 400,
            ErrorCode.INVALID_IP_ADDRESS: 400,
            ErrorCode.API_KEY_INVALID: 401,
            ErrorCode.ACCESS_DENIED: 403,
            ErrorCode.TILE_NOT_FOUND: 404,
            ErrorCode.ELEVATION_NOT_AVAILABLE: 404,
            ErrorCode.RATE_LIMIT_EXCEEDED: 429,
            ErrorCode.INTERNAL_SERVER_ERROR: 500,
            ErrorCode.SERVICE_UNAVAILABLE: 503,
            ErrorCode.TILESERVER_UNAVAILABLE: 503,
            ErrorCode.REDIS_CONNECTION_FAILED: 503,
        }
        
        status_code = status_code_map.get(error.error_code, 500)
        
        return HTTPException(
            status_code=status_code,
            detail=error.to_dict()
        )


# Global error handler instance
error_handler = ErrorHandler()


def handle_elevation_data_error(func):
    """Decorator for elevation data operations."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_handler.logger.error(f"Elevation data error in {func.__name__}: {e}", exc_info=True)
            raise ElevationDataError(
                ErrorCode.ELEVATION_DATA_CORRUPT,
                f"Failed to process elevation data: {str(e)}",
                cause=e
            )
    return wrapper


def handle_tile_service_error(func):
    """Decorator for tile service operations."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_handler.logger.error(f"Tile service error in {func.__name__}: {e}", exc_info=True)
            raise TileServiceError(
                ErrorCode.TILESERVER_UNAVAILABLE,
                f"Tile service error: {str(e)}",
                cause=e
            )
    return wrapper


def validate_coordinates(latitude: float, longitude: float) -> None:
    """Validate geographic coordinates."""
    if not (-90 <= latitude <= 90):
        raise ValidationError(
            ErrorCode.INVALID_COORDINATES,
            f"Latitude {latitude} is out of valid range (-90 to 90)",
            suggestions=["Ensure latitude is between -90 and 90 degrees"]
        )
    
    if not (-180 <= longitude <= 180):
        raise ValidationError(
            ErrorCode.INVALID_COORDINATES,
            f"Longitude {longitude} is out of valid range (-180 to 180)",
            suggestions=["Ensure longitude is between -180 and 180 degrees"]
        )


def validate_tile_coordinates(z: int, x: int, y: int) -> None:
    """Validate tile coordinates."""
    if z < 0 or z > 25:
        raise ValidationError(
            ErrorCode.INVALID_TILE_COORDINATES,
            f"Zoom level {z} is out of valid range (0 to 25)"
        )
    
    max_coord = (1 << z) - 1
    if x < 0 or x > max_coord:
        raise ValidationError(
            ErrorCode.INVALID_TILE_COORDINATES,
            f"Tile X coordinate {x} is out of valid range (0 to {max_coord}) for zoom {z}"
        )
    
    if y < 0 or y > max_coord:
        raise ValidationError(
            ErrorCode.INVALID_TILE_COORDINATES,
            f"Tile Y coordinate {y} is out of valid range (0 to {max_coord}) for zoom {z}"
        )


def validate_water_level(water_level: float) -> None:
    """Validate water level parameter."""
    if not (0 <= water_level <= 100):
        raise ValidationError(
            ErrorCode.INVALID_WATER_LEVEL,
            f"Water level {water_level} is out of valid range (0 to 100 meters)",
            suggestions=["Water level should be between 0 and 100 meters"]
        )


def validate_elevation_data(data: np.ndarray, expected_shape: tuple = None) -> None:
    """Validate elevation data integrity."""
    if data is None:
        raise ElevationDataError(
            ErrorCode.ELEVATION_DATA_MISSING,
            "Elevation data is None"
        )
    
    if not isinstance(data, np.ndarray):
        raise ElevationDataError(
            ErrorCode.ELEVATION_DATA_CORRUPT,
            f"Elevation data is not a numpy array: {type(data)}"
        )
    
    if expected_shape and data.shape != expected_shape:
        raise ElevationDataError(
            ErrorCode.ELEVATION_DATA_CORRUPT,
            f"Elevation data shape {data.shape} does not match expected {expected_shape}"
        )
    
    # Check for all no-data values
    if np.all(data == -32768):
        raise ElevationDataError(
            ErrorCode.ELEVATION_DATA_MISSING,
            "Elevation data contains only no-data values"
        )
    
    # Check for all invalid values
    if not np.isfinite(data).any():
        raise ElevationDataError(
            ErrorCode.ELEVATION_DATA_CORRUPT,
            "Elevation data contains only invalid values"
        )
    
    # Check for reasonable elevation range (SRTM: -500 to 9000 meters)
    valid_data = data[data != -32768]
    if len(valid_data) > 0:
        min_elev, max_elev = np.min(valid_data), np.max(valid_data)
        if min_elev < -500 or max_elev > 9000:
            error_handler.logger.warning(
                f"Elevation data has unusual range: {min_elev} to {max_elev} meters"
            )


async def handle_external_service_error(
    service_name: str, 
    operation: str, 
    error: Exception
) -> None:
    """Standard handling for external service errors."""
    
    error_code_map = {
        "timeout": ErrorCode.TILESERVER_TIMEOUT,
        "connection": ErrorCode.TILESERVER_UNAVAILABLE,
        "redis": ErrorCode.REDIS_CONNECTION_FAILED,
    }
    
    error_type = "connection"
    if "timeout" in str(error).lower():
        error_type = "timeout"
    elif "redis" in service_name.lower():
        error_type = "redis"
    
    error_code = error_code_map.get(error_type, ErrorCode.SERVICE_UNAVAILABLE)
    
    raise ExternalServiceError(
        error_code,
        f"{service_name} {operation} failed: {str(error)}",
        details={"service": service_name, "operation": operation},
        cause=error
    )


# Exception handler for FastAPI
async def floodmap_exception_handler(request: Request, exc: FloodMapError):
    """Global exception handler for FloodMap errors."""
    error_handler.log_error(exc, request)
    
    return JSONResponse(
        status_code=error_handler.create_http_exception(exc).status_code,
        content=exc.to_dict()
    )