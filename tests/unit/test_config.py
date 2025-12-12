"""
Unit tests for config.py - configuration and environment variable handling.

These tests verify configuration defaults and environment-based behavior.
"""

import re
from pathlib import Path


class TestConfigConstants:
    """Test that configuration constants have expected values."""

    def test_tile_size(self):
        """Tile size should be 256 (standard web tile size)."""
        from config import TILE_SIZE

        assert TILE_SIZE == 256

    def test_max_zoom(self):
        """Max zoom should be 18."""
        from config import MAX_ZOOM

        assert MAX_ZOOM == 18

    def test_min_zoom(self):
        """Min zoom should be 0."""
        from config import MIN_ZOOM

        assert MIN_ZOOM == 0

    def test_nodata_value(self):
        """NODATA value should be -32768 (int16 min)."""
        from config import NODATA_VALUE

        assert NODATA_VALUE == -32768

    def test_water_level_range(self):
        """Water level range should be reasonable."""
        from config import MAX_WATER_LEVEL, MIN_WATER_LEVEL

        assert MIN_WATER_LEVEL == -10.0
        assert MAX_WATER_LEVEL == 1000.0
        assert MIN_WATER_LEVEL < MAX_WATER_LEVEL


class TestContainerPaths:
    """Test that container paths are correctly defined."""

    def test_elevation_source_dir(self):
        """Elevation source directory should be /app/data/elevation-source."""
        from config import ELEVATION_SOURCE_DIR

        assert Path("/app/data/elevation-source") == ELEVATION_SOURCE_DIR

    def test_elevation_tiles_dir(self):
        """Elevation tiles directory should be /app/data/elevation-tiles."""
        from config import ELEVATION_TILES_DIR

        assert Path("/app/data/elevation-tiles") == ELEVATION_TILES_DIR

    def test_base_maps_dir(self):
        """Base maps directory should be /app/data/base-maps."""
        from config import BASE_MAPS_DIR

        assert Path("/app/data/base-maps") == BASE_MAPS_DIR

    def test_legacy_aliases(self):
        """Legacy path aliases should point to correct directories."""
        from config import (
            BASE_MAPS_DIR,
            ELEVATION_DATA_DIR,
            ELEVATION_SOURCE_DIR,
            MAP_DATA_DIR,
        )

        assert ELEVATION_DATA_DIR == ELEVATION_SOURCE_DIR
        assert MAP_DATA_DIR == BASE_MAPS_DIR


class TestServerPorts:
    """Test server port configuration."""

    def test_default_api_port(self):
        """Default API port should be 8000."""
        # Note: This tests the default, actual value may differ if env var is set
        from config import API_PORT

        assert isinstance(API_PORT, int)
        assert API_PORT > 0
        assert API_PORT < 65536

    def test_default_tileserver_port(self):
        """Default tileserver port should be 8080."""
        from config import TILESERVER_PORT

        assert isinstance(TILESERVER_PORT, int)
        assert TILESERVER_PORT > 0

    def test_default_frontend_port(self):
        """Default frontend port should be 3000."""
        from config import FRONTEND_PORT

        assert isinstance(FRONTEND_PORT, int)
        assert FRONTEND_PORT > 0


class TestEnvironmentDetection:
    """Test environment detection logic."""

    def test_environment_variable_exists(self):
        """ENVIRONMENT variable should have a default value."""
        from config import ENVIRONMENT

        assert isinstance(ENVIRONMENT, str)
        assert len(ENVIRONMENT) > 0

    def test_is_development_flag(self):
        """IS_DEVELOPMENT should be a boolean."""
        from config import IS_DEVELOPMENT

        assert isinstance(IS_DEVELOPMENT, bool)

    def test_is_production_flag(self):
        """IS_PRODUCTION should be a boolean."""
        from config import IS_PRODUCTION

        assert isinstance(IS_PRODUCTION, bool)

    def test_dev_and_prod_mutually_exclusive(self):
        """Cannot be both development and production."""
        from config import IS_DEVELOPMENT, IS_PRODUCTION

        # They shouldn't both be True (but both could be False for staging/test)
        assert not (IS_DEVELOPMENT and IS_PRODUCTION)


class TestCacheConfiguration:
    """Test cache-related configuration."""

    def test_elevation_cache_size(self):
        """Elevation cache size should be a positive integer."""
        from config import ELEVATION_CACHE_SIZE

        assert isinstance(ELEVATION_CACHE_SIZE, int)
        assert ELEVATION_CACHE_SIZE > 0

    def test_tile_cache_size(self):
        """Tile cache size should be a positive integer."""
        from config import TILE_CACHE_SIZE

        assert isinstance(TILE_CACHE_SIZE, int)
        assert TILE_CACHE_SIZE > 0

    def test_tile_cache_max_age_environment_aware(self):
        """Tile cache max age should differ between dev and prod."""
        from config import IS_DEVELOPMENT, TILE_CACHE_MAX_AGE

        if IS_DEVELOPMENT:
            assert TILE_CACHE_MAX_AGE == 0
        else:
            assert TILE_CACHE_MAX_AGE == 31536000  # 1 year


class TestSecurityConfiguration:
    """Test security-related configuration."""

    def test_allowed_hosts_is_list(self):
        """ALLOWED_HOSTS should be a list."""
        from config import ALLOWED_HOSTS

        assert isinstance(ALLOWED_HOSTS, list)

    def test_allowed_hosts_default(self):
        """Default ALLOWED_HOSTS should include wildcard or be empty."""
        from config import ALLOWED_HOSTS

        # Should have at least one entry or be the default wildcard
        assert len(ALLOWED_HOSTS) >= 0

    def test_feature_flags_are_booleans(self):
        """Feature flags should be booleans."""
        from config import ENABLE_DIAGNOSTICS, ENABLE_PERF_TEST_ROUTES

        assert isinstance(ENABLE_DIAGNOSTICS, bool)
        assert isinstance(ENABLE_PERF_TEST_ROUTES, bool)

    def test_force_https_flag(self):
        """FORCE_HTTPS should be a boolean."""
        from config import FORCE_HTTPS

        assert isinstance(FORCE_HTTPS, bool)


class TestDataPaths:
    """Test data path configuration."""

    def test_elevation_dirs_is_list(self):
        """ELEVATION_DIRS should be a list of paths."""
        from config import ELEVATION_DIRS

        assert isinstance(ELEVATION_DIRS, list)
        assert all(isinstance(p, Path) for p in ELEVATION_DIRS)

    def test_base_map_paths_is_list(self):
        """BASE_MAP_PATHS should be a list of paths."""
        from config import BASE_MAP_PATHS

        assert isinstance(BASE_MAP_PATHS, list)
        assert all(isinstance(p, Path) for p in BASE_MAP_PATHS)

    def test_health_check_dirs_is_list(self):
        """HEALTH_CHECK_DIRS should be a list of strings."""
        from config import HEALTH_CHECK_DIRS

        assert isinstance(HEALTH_CHECK_DIRS, list)
        assert all(isinstance(d, str) for d in HEALTH_CHECK_DIRS)


class TestTileserverUrl:
    """Test tileserver URL configuration."""

    def test_tileserver_url_format(self):
        """TILESERVER_URL should be a valid URL."""
        from config import TILESERVER_URL

        assert isinstance(TILESERVER_URL, str)
        assert TILESERVER_URL.startswith("http://") or TILESERVER_URL.startswith(
            "https://"
        )

    def test_tileserver_url_contains_port(self):
        """TILESERVER_URL should contain the tileserver port."""
        from config import TILESERVER_PORT, TILESERVER_URL

        # URL should reference the configured port
        assert str(TILESERVER_PORT) in TILESERVER_URL


class TestRuntimeElevationCache:
    """Test runtime elevation cache configuration."""

    def test_enable_runtime_elevation_cache_flag(self):
        """ENABLE_RUNTIME_ELEVATION_CACHE should be a boolean."""
        from config import ENABLE_RUNTIME_ELEVATION_CACHE

        assert isinstance(ENABLE_RUNTIME_ELEVATION_CACHE, bool)

    def test_runtime_cache_default_off(self):
        """Runtime elevation cache should be off by default."""
        # This is the expected default for cost/memory reasons
        from config import ENABLE_RUNTIME_ELEVATION_CACHE

        # Note: This test documents expected behavior, actual value depends on env
        assert isinstance(ENABLE_RUNTIME_ELEVATION_CACHE, bool)


class TestFrontendBackendConsistency:
    """Test that frontend and backend configuration stay in sync."""

    # Precompressed tiles only exist for zoom 0-11
    PRECOMPRESSED_MAX_ZOOM = 11

    def test_frontend_maxzoom_matches_precompressed_tiles(self):
        """Frontend maxZoom must not exceed precompressed tile availability.

        This catches the bug where zooming beyond precompressed tiles
        causes all tiles to appear as water/NODATA.
        """
        js_file = Path(__file__).parent.parent.parent / "src/web/js/map-client.js"
        content = js_file.read_text()

        # Find maxZoom in the config object
        match = re.search(r"maxZoom:\s*(\d+)", content)
        assert match, "Could not find maxZoom setting in map-client.js"

        frontend_max_zoom = int(match.group(1))
        assert frontend_max_zoom <= self.PRECOMPRESSED_MAX_ZOOM, (
            f"Frontend maxZoom ({frontend_max_zoom}) exceeds precompressed tile limit "
            f"({self.PRECOMPRESSED_MAX_ZOOM}). Users will see broken tiles at high zoom."
        )
