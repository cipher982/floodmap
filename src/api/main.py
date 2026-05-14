"""
Clean FastAPI-only flood mapping application.
Single server architecture with clear separation of concerns.
"""

import logging
import math
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

# Get logger
logger = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
FAVICON_SVG_PATH = WEB_DIR / "favicon.svg"
DRAINAGE_LAB_HTML_PATH = WEB_DIR / "drainage-lab.html"
DRAINAGE_LAB_TILES_DIR = WEB_DIR / "prototypes" / "birmingham-drainage" / "tiles"
DRAINAGE_LAB_SAMPLE_ZOOM = 12
MAPLIBRE_CSP_JS_GZ_PATH = WEB_DIR / "vendor" / "maplibre-gl-csp-4.7.1.js.gz"
MAPLIBRE_CSP_WORKER_GZ_PATH = WEB_DIR / "vendor" / "maplibre-gl-csp-worker-4.7.1.js.gz"
PRECOMPRESSED_VENDOR_HEADERS = {
    "Cache-Control": "public, max-age=31536000, immutable",
    "Content-Encoding": "gzip",
    "Vary": "Accept-Encoding",
}
ZIP_NOINDEX_HEADERS = {"X-Robots-Tag": "noindex, follow"}

# OpenTelemetry imports
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Load environment variables from .env file
load_dotenv()


# Critical data validation on startup
def validate_critical_data():
    """Validate that all critical data files exist and are accessible.
    Uses fixed container paths from config and does not terminate the app.
    """
    from pathlib import Path

    # Use fixed container paths from config
    from config import ELEVATION_DATA_DIR, MAP_DATA_DIR

    elevation_dir: Path = ELEVATION_DATA_DIR
    mbtiles_file: Path = MAP_DATA_DIR / "usa-complete.mbtiles"

    errors = []
    warnings = []

    # Check elevation data directory
    if not elevation_dir.exists():
        errors.append(f"CRITICAL: Elevation data directory missing: {elevation_dir}")
    else:
        elevation_files = list(elevation_dir.glob("*.zst"))
        if len(elevation_files) < 1000:  # Should have 2000+ files in full dataset
            errors.append(
                f"CRITICAL: Insufficient elevation files: {len(elevation_files)} (expected 2000+)"
            )
        elif len(elevation_files) < 2000:
            warnings.append(
                f"WARNING: Low elevation file count: {len(elevation_files)} (expected 2000+)"
            )

    # Check MBTiles file
    if not mbtiles_file.exists():
        errors.append(f"CRITICAL: MBTiles file missing: {mbtiles_file}")
    else:
        size_gb = mbtiles_file.stat().st_size / (1024**3)
        if size_gb < 1.0:  # Should be ~1.6GB
            errors.append(
                f"CRITICAL: MBTiles file too small: {size_gb:.1f}GB (expected ~1.6GB)"
            )

    # Log results without terminating the process
    if errors:
        print("🚨 STARTUP VALIDATION FAILED:")
        for error in errors:
            print(f"  ❌ {error}")
        if warnings:
            for warning in warnings:
                print(f"  ⚠️  {warning}")
        print("\n💡 Check your host bind mounts and data presence.")
        print("   Elevation: /app/data/elevation | Maps: /app/data/maps")

        # In development/tests, allow booting with partial data so CI/local can run.
        # Endpoints that require real data will still fail explicitly.
        if os.getenv("ALLOW_MISSING_DATA", "false").lower() in ("1", "true", "yes"):
            print(
                "⚠️  ALLOW_MISSING_DATA enabled; continuing startup despite missing data."
            )
        else:
            # In production, missing critical data should fail fast.
            if os.getenv("ENVIRONMENT", "production").lower() in ("production", "prod"):
                raise RuntimeError(
                    "Critical data missing; refusing to start in production."
                )
    elif warnings:
        print("⚠️  STARTUP WARNINGS:")
        for warning in warnings:
            print(f"  {warning}")
    else:
        print("✅ Data validation passed - all critical files present")
        # Show access URLs for development
        from config import IS_DEVELOPMENT

        if IS_DEVELOPMENT:
            api_port = os.getenv("API_PORT", "8000")
            tileserver_port = os.getenv("TILESERVER_PORT", "8080")
            print(f"🌐 Local development server: http://localhost:{api_port}")
            print(f"🔧 Local tileserver: http://localhost:{tileserver_port}")


# Configure OpenTelemetry
def configure_telemetry():
    """Configure OpenTelemetry with ClickHouse backend."""
    # Only configure if ClickHouse connection details are provided
    otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not otel_endpoint:
        return

    resource = Resource.create(
        {
            "service.name": "floodmap-api",
            "service.version": "2.0.0",
            "deployment.environment": os.getenv("ENVIRONMENT", "development"),
        }
    )

    trace.set_tracer_provider(TracerProvider(resource=resource))

    # Configure OTLP exporter using gRPC
    otlp_exporter = OTLPSpanExporter(
        endpoint=otel_endpoint,
        insecure=True,  # Internal network, no TLS needed
    )

    span_processor = BatchSpanProcessor(otlp_exporter)
    trace.get_tracer_provider().add_span_processor(span_processor)


# Initialize telemetry
configure_telemetry()

# Validate critical data on startup
validate_critical_data()

# Import routers
from config import (
    ALLOWED_HOSTS,
    ENABLE_DIAGNOSTICS,
    ENABLE_PERF_TEST_ROUTES,
    FORCE_HTTPS,
    IS_DEVELOPMENT,
)
from location_catalog import get_city_page, get_zip_page

# Import middleware
from middleware.rate_limiter import RateLimitMiddleware
from page_renderer import (
    build_city_page_html,
    build_home_page_html,
    build_zip_page_html,
)
from routers import diagnostics as diagnostics_router
from routers import health, places, risk, tiles_performance_test, tiles_v1
from sitemaps import (
    build_city_sitemap_xml,
    build_pages_sitemap_xml,
    build_sitemap_index_xml,
)

# Create FastAPI app
app = FastAPI(
    title="Flood Risk Map API",
    description="Clean flood risk mapping service",
    version="2.0.0",
)


# HTTP client lifecycle management
@app.on_event("startup")
async def startup_event():
    """Initialize shared HTTP client on startup."""
    try:
        from http_client import get_http_client

        client = await get_http_client()  # Initialize the client
        logger.info("🔗 HTTP client initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize HTTP client: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up shared HTTP client on shutdown."""
    try:
        from http_client import close_http_client

        await close_http_client()
        logger.info("🔒 HTTP client closed successfully")
    except Exception as e:
        logger.error(f"❌ Failed to close HTTP client: {e}")


# Add middleware
app.add_middleware(RateLimitMiddleware, default_limit=60)

# Trusted hosts (mitigates Host header attacks)
if ALLOWED_HOSTS:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

# Enforce HTTPS redirects if configured (common in production behind proxy)
if FORCE_HTTPS:
    app.add_middleware(HTTPSRedirectMiddleware)


# Minimal security headers for all responses
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    # Safe, broadly-applicable defaults
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "cross-origin")
    return response


# Instrument FastAPI with OpenTelemetry
if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
    FastAPIInstrumentor.instrument_app(app)
    RequestsInstrumentor().instrument()

# Include API routers
app.include_router(health.router, prefix="/api", tags=["health"])

# Diagnostics and performance routes are disabled in production by default
if IS_DEVELOPMENT or ENABLE_DIAGNOSTICS:
    app.include_router(diagnostics_router.router)  # /api/diagnostics

app.include_router(
    tiles_v1.router, tags=["tiles-v1"]
)  # New v1 routes (already prefixed)

if IS_DEVELOPMENT or ENABLE_PERF_TEST_ROUTES:
    app.include_router(
        tiles_performance_test.router, tags=["performance-testing"]
    )  # Perf test routes

app.include_router(risk.router, prefix="/api", tags=["risk"])
app.include_router(places.router, prefix="/api", tags=["places"])


def _lonlat_to_tile_pixel(
    lon: float, lat: float, zoom: int
) -> tuple[int, int, int, int]:
    clipped_lat = max(-85.05112878, min(85.05112878, lat))
    scale = 2**zoom
    x_float = (lon + 180.0) / 360.0 * scale
    lat_rad = math.radians(clipped_lat)
    y_float = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * scale
    tile_x = int(math.floor(x_float))
    tile_y = int(math.floor(y_float))
    pixel_x = min(255, max(0, int((x_float - tile_x) * 256)))
    pixel_y = min(255, max(0, int((y_float - tile_y) * 256)))
    return tile_x, tile_y, pixel_x, pixel_y


async def drainage_lab_sample_impl(lat: float, lng: float):
    """Sample the one-off Birmingham drainage-height prototype."""
    import numpy as np

    tile_x, tile_y, pixel_x, pixel_y = _lonlat_to_tile_pixel(
        lng, lat, DRAINAGE_LAB_SAMPLE_ZOOM
    )
    tile_path = (
        DRAINAGE_LAB_TILES_DIR
        / str(DRAINAGE_LAB_SAMPLE_ZOOM)
        / str(tile_x)
        / f"{tile_y}.u16"
    )
    if not tile_path.exists():
        raise HTTPException(status_code=404, detail="Point outside prototype area")

    values = np.frombuffer(tile_path.read_bytes(), dtype=np.uint16).reshape((256, 256))
    value = int(values[pixel_y, pixel_x])
    if value == 65535:
        raise HTTPException(status_code=404, detail="Point outside prototype area")

    height_m = value / 10.0
    return {
        "latitude": lat,
        "longitude": lng,
        "height_m": round(height_m, 2),
        "height_ft": round(height_m * 3.28084, 1),
        "nearest_stream": "downstream drainage",
        "model": "prototype-flow-path-hand-tile-sample",
    }


@app.get("/api/prototype/birmingham-drainage/sample")
async def drainage_lab_sample(lat: float, lng: float):
    return await drainage_lab_sample_impl(lat, lng)


@app.get("/floodmap/api/prototype/birmingham-drainage/sample")
async def drainage_lab_sample_floodmap(lat: float, lng: float):
    return await drainage_lab_sample_impl(lat, lng)


def _serve_precompressed_vendor_asset(
    asset_path: Path, *, media_type: str
) -> FileResponse:
    return FileResponse(
        asset_path,
        media_type=media_type,
        headers=dict(PRECOMPRESSED_VENDOR_HEADERS),
    )


@app.get("/static/vendor/maplibre-gl-csp-4.7.1.js", include_in_schema=False)
async def vendored_maplibre_csp_js():
    return _serve_precompressed_vendor_asset(
        MAPLIBRE_CSP_JS_GZ_PATH, media_type="text/javascript"
    )


@app.get("/floodmap/static/vendor/maplibre-gl-csp-4.7.1.js", include_in_schema=False)
async def vendored_maplibre_csp_js_floodmap():
    return await vendored_maplibre_csp_js()


@app.get("/static/vendor/maplibre-gl-csp-worker-4.7.1.js", include_in_schema=False)
async def vendored_maplibre_csp_worker():
    return _serve_precompressed_vendor_asset(
        MAPLIBRE_CSP_WORKER_GZ_PATH, media_type="text/javascript"
    )


@app.get(
    "/floodmap/static/vendor/maplibre-gl-csp-worker-4.7.1.js",
    include_in_schema=False,
)
async def vendored_maplibre_csp_worker_floodmap():
    return await vendored_maplibre_csp_worker()


# Serve static frontend files
#
# Production is hosted under a `/floodmap` subpath (reverse proxy), but local
# dev/tests commonly run at `/`. Mount both so local E2E works.
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
app.mount(
    "/floodmap/static", StaticFiles(directory=str(WEB_DIR)), name="static_floodmap"
)


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main application frontend."""
    return HTMLResponse(content=build_home_page_html())


@app.api_route("/floodmap/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_frontend_floodmap():
    """Serve the frontend when hosted under the /floodmap subpath."""
    return await serve_frontend()


@app.api_route("/drainage-lab", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_drainage_lab():
    """Serve the one-off Birmingham drainage-height prototype."""
    if not DRAINAGE_LAB_HTML_PATH.exists():
        raise HTTPException(status_code=404, detail="Drainage lab not found")
    return HTMLResponse(content=DRAINAGE_LAB_HTML_PATH.read_text(encoding="utf-8"))


@app.api_route(
    "/floodmap/drainage-lab", methods=["GET", "HEAD"], response_class=HTMLResponse
)
async def serve_drainage_lab_floodmap():
    return await serve_drainage_lab()


@app.get("/favicon.svg", include_in_schema=False)
async def favicon_svg():
    """Serve the app's SVG favicon from the static web directory."""
    try:
        return Response(
            content=FAVICON_SVG_PATH.read_text(encoding="utf-8"),
            media_type="image/svg+xml",
        )
    except Exception:
        # Fallback to a simple emoji-based favicon if file missing
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
            "<text x='50%' y='50%' dominant-baseline='central' text-anchor='middle' font-size='52'>🌊</text>"
            "</svg>"
        )
        return Response(content=svg, media_type="image/svg+xml")


@app.get("/floodmap/favicon.svg", include_in_schema=False)
async def favicon_svg_floodmap():
    return await favicon_svg()


@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    """Redirect .ico requests to the SVG favicon to avoid 404s."""
    return RedirectResponse(url="favicon.svg")


@app.get("/floodmap/favicon.ico", include_in_schema=False)
async def favicon_ico_floodmap():
    return RedirectResponse(url="favicon.svg")


def _build_site_manifest() -> Response:
    """Build a minimal path-relative web app manifest for installability."""
    manifest = {
        "name": "FloodMap USA",
        "short_name": "FloodMap",
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "background_color": "#0d47a1",
        "theme_color": "#0d47a1",
        "icons": [
            {
                "src": "favicon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any maskable",
            }
        ],
    }
    import json

    return Response(
        content=json.dumps(manifest), media_type="application/manifest+json"
    )


@app.get("/site.webmanifest", include_in_schema=False)
async def site_manifest():
    """Serve a manifest that works at either root or /floodmap."""
    return _build_site_manifest()


@app.get("/floodmap/site.webmanifest", include_in_schema=False)
async def site_manifest_floodmap():
    """Serve the same path-relative manifest on the /floodmap subpath."""
    return _build_site_manifest()


def _build_xml_response(content: str) -> Response:
    return Response(content=content, media_type="application/xml")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_index():
    return _build_xml_response(build_sitemap_index_xml())


@app.get("/floodmap/sitemap.xml", include_in_schema=False)
async def sitemap_index_floodmap():
    return _build_xml_response(build_sitemap_index_xml())


@app.get("/sitemaps/pages.xml", include_in_schema=False)
async def pages_sitemap():
    return _build_xml_response(build_pages_sitemap_xml())


@app.get("/floodmap/sitemaps/pages.xml", include_in_schema=False)
async def pages_sitemap_floodmap():
    return _build_xml_response(build_pages_sitemap_xml())


@app.get("/sitemaps/cities.xml", include_in_schema=False)
async def cities_sitemap():
    return _build_xml_response(build_city_sitemap_xml())


@app.get("/floodmap/sitemaps/cities.xml", include_in_schema=False)
async def cities_sitemap_floodmap():
    return _build_xml_response(build_city_sitemap_xml())


@app.api_route("/zip/{zip_code}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_zip_frontend(zip_code: str):
    """Serve conservative ZIP landing pages at the domain root for local/dev use."""
    zip_page = get_zip_page(zip_code)
    if zip_page is None:
        raise HTTPException(status_code=404, detail="ZIP page not found")
    return HTMLResponse(
        content=build_zip_page_html(zip_page),
        headers=dict(ZIP_NOINDEX_HEADERS),
    )


@app.api_route(
    "/floodmap/zip/{zip_code}",
    methods=["GET", "HEAD"],
    response_class=HTMLResponse,
)
async def serve_zip_frontend_floodmap(zip_code: str):
    """Serve the same ZIP landing pages when hosted under the /floodmap subpath."""
    return await serve_zip_frontend(zip_code)


@app.api_route(
    "/{state_slug}/{city_slug}", methods=["GET", "HEAD"], response_class=HTMLResponse
)
async def serve_city_frontend(state_slug: str, city_slug: str):
    """Serve crawlable city landing pages at the domain root for local/dev use."""
    city_page = get_city_page(state_slug, city_slug)
    if city_page is None:
        raise HTTPException(status_code=404, detail="City page not found")
    return HTMLResponse(content=build_city_page_html(city_page))


@app.api_route(
    "/floodmap/{state_slug}/{city_slug}",
    methods=["GET", "HEAD"],
    response_class=HTMLResponse,
)
async def serve_city_frontend_floodmap(state_slug: str, city_slug: str):
    """Serve the same city landing pages when hosted under the /floodmap subpath."""
    return await serve_city_frontend(state_slug, city_slug)


if __name__ == "__main__":
    import os

    # Get port from environment or use default
    port = int(os.getenv("API_PORT", "8000"))

    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True, log_level="info")
