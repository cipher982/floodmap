"""Tests for error handling framework."""
import pytest
import numpy as np
from unittest.mock import Mock, patch

# Import error handling components
from error_handling import (
    ErrorCode, 
    FloodMapError, 
    ElevationDataError, 
    TileServiceError,
    ValidationError,
    ExternalServiceError,
    RateLimitError,
    validate_coordinates,
    validate_tile_coordinates,
    validate_water_level,
    validate_elevation_data,
    ErrorHandler
)


@pytest.mark.unit
class TestErrorCodes:
    """Test error code definitions."""
    
    def test_error_codes_exist(self):
        """Test that all expected error codes are defined."""
        expected_codes = [
            "ELEVATION_DATA_CORRUPT",
            "ELEVATION_DATA_MISSING", 
            "TILESERVER_UNAVAILABLE",
            "INVALID_COORDINATES",
            "TILE_NOT_FOUND",
            "RATE_LIMIT_EXCEEDED"
        ]
        
        for code in expected_codes:
            assert hasattr(ErrorCode, code), f"Missing error code: {code}"


@pytest.mark.unit
class TestCoordinateValidation:
    """Test coordinate validation functions."""
    
    def test_valid_coordinates(self):
        """Test validation of valid coordinates."""
        valid_coords = [
            (0, 0),           # Origin
            (27.9506, -82.4585),  # Tampa
            (-90, -180),      # SW corner
            (90, 180),        # NE corner
        ]
        
        for lat, lon in valid_coords:
            # Should not raise exception
            validate_coordinates(lat, lon)
    
    def test_invalid_coordinates(self):
        """Test validation of invalid coordinates."""
        invalid_coords = [
            (91, 0),      # Latitude too high
            (-91, 0),     # Latitude too low
            (0, 181),     # Longitude too high
            (0, -181),    # Longitude too low
            (100, 200),   # Both invalid
        ]
        
        for lat, lon in invalid_coords:
            with pytest.raises(ValidationError):
                validate_coordinates(lat, lon)
    
    def test_tile_coordinate_validation(self):
        """Test tile coordinate validation."""
        # Valid coordinates
        validate_tile_coordinates(10, 512, 512)  # Should not raise
        validate_tile_coordinates(0, 0, 0)       # Should not raise
        
        # Invalid coordinates
        with pytest.raises(ValidationError):
            validate_tile_coordinates(-1, 0, 0)  # Negative zoom
        
        with pytest.raises(ValidationError):
            validate_tile_coordinates(10, 2000, 0)  # X too high for zoom
    
    def test_water_level_validation(self):
        """Test water level validation."""
        # Valid levels
        validate_water_level(0)      # Should not raise
        validate_water_level(50.5)   # Should not raise
        validate_water_level(100)    # Should not raise
        
        # Invalid levels
        with pytest.raises(ValidationError):
            validate_water_level(-1)   # Negative
        
        with pytest.raises(ValidationError):
            validate_water_level(101)  # Too high


@pytest.mark.unit
class TestElevationDataValidation:
    """Test elevation data validation."""
    
    def test_valid_elevation_data(self):
        """Test validation of valid elevation data."""
        # Create valid test data
        data = np.array([[100, 200, 150], [180, 220, 190]], dtype=np.int16)
        
        # Should not raise exception
        validate_elevation_data(data)
    
    def test_invalid_elevation_data(self):
        """Test validation of invalid elevation data."""
        # None data
        with pytest.raises(ElevationDataError):
            validate_elevation_data(None)
        
        # Wrong type
        with pytest.raises(ElevationDataError):
            validate_elevation_data("not_an_array")
        
        # All no-data values
        no_data = np.full((10, 10), -32768, dtype=np.int16)
        with pytest.raises(ElevationDataError):
            validate_elevation_data(no_data)
        
        # All invalid values
        invalid_data = np.full((10, 10), np.nan, dtype=np.float32)
        with pytest.raises(ElevationDataError):
            validate_elevation_data(invalid_data)
    
    def test_elevation_data_shape_validation(self):
        """Test shape validation for elevation data."""
        data = np.array([[100, 200], [150, 180]], dtype=np.int16)
        expected_shape = (2, 2)
        
        # Should not raise exception
        validate_elevation_data(data, expected_shape)
        
        # Wrong shape should raise exception
        wrong_shape = (3, 3)
        with pytest.raises(ElevationDataError):
            validate_elevation_data(data, wrong_shape)


@pytest.mark.unit
class TestFloodMapError:
    """Test FloodMapError exception class."""
    
    def test_error_creation(self):
        """Test basic error creation."""
        error = FloodMapError(
            ErrorCode.ELEVATION_DATA_MISSING,
            "Test error message",
            details={"test": "value"}
        )
        
        assert error.error_code == ErrorCode.ELEVATION_DATA_MISSING
        assert error.message == "Test error message"
        assert error.details["test"] == "value"
        assert len(error.request_id) > 0
        assert error.timestamp is not None
    
    def test_error_serialization(self):
        """Test error serialization to dict."""
        error = FloodMapError(
            ErrorCode.TILE_NOT_FOUND,
            "Tile not found",
            suggestions=["Try a different zoom level"]
        )
        
        error_dict = error.to_dict()
        
        assert error_dict["error"] == "TILE_NOT_FOUND"
        assert error_dict["message"] == "Tile not found"
        assert "Try a different zoom level" in error_dict["suggestions"]
        assert "timestamp" in error_dict
        assert "request_id" in error_dict
    
    def test_default_user_messages(self):
        """Test default user-friendly messages."""
        error = ElevationDataError(
            ErrorCode.ELEVATION_DATA_MISSING,
            "Technical message"
        )
        
        # Should have user-friendly message
        assert "not available" in error.user_message.lower()
        assert error.user_message != error.message


@pytest.mark.unit
class TestErrorHandler:
    """Test error handler functionality."""
    
    def test_error_handler_creation(self):
        """Test error handler creation."""
        handler = ErrorHandler()
        assert handler.logger is not None
    
    def test_http_exception_creation(self):
        """Test HTTP exception creation from FloodMapError."""
        handler = ErrorHandler()
        
        error = ValidationError(
            ErrorCode.INVALID_COORDINATES,
            "Invalid coordinates"
        )
        
        http_exc = handler.create_http_exception(error)
        
        assert http_exc.status_code == 400
        assert isinstance(http_exc.detail, dict)
        assert http_exc.detail["error"] == "INVALID_COORDINATES"
    
    @patch('error_handling.logging')
    def test_error_logging(self, mock_logging):
        """Test error logging functionality."""
        handler = ErrorHandler()
        
        error = FloodMapError(
            ErrorCode.INTERNAL_SERVER_ERROR,
            "Test error"
        )
        
        # Should not raise exception
        handler.log_error(error)
        
        # Should have called logger
        assert mock_logging.getLogger.called


@pytest.mark.unit
class TestSpecificErrorTypes:
    """Test specific error type functionality."""
    
    def test_elevation_data_error(self):
        """Test ElevationDataError specifics."""
        error = ElevationDataError(
            ErrorCode.ELEVATION_DATA_CORRUPT,
            "Data corrupt"
        )
        
        assert isinstance(error, FloodMapError)
        assert error.error_code == ErrorCode.ELEVATION_DATA_CORRUPT
    
    def test_tile_service_error(self):
        """Test TileServiceError specifics."""
        error = TileServiceError(
            ErrorCode.TILESERVER_UNAVAILABLE,
            "Service down"
        )
        
        assert isinstance(error, FloodMapError)
        assert error.error_code == ErrorCode.TILESERVER_UNAVAILABLE
    
    def test_rate_limit_error(self):
        """Test RateLimitError specifics."""
        error = RateLimitError(
            ErrorCode.RATE_LIMIT_EXCEEDED,
            "Too many requests",
            suggestions=["Wait before retrying"]
        )
        
        assert isinstance(error, FloodMapError)
        assert error.error_code == ErrorCode.RATE_LIMIT_EXCEEDED
        assert "Wait before retrying" in error.suggestions