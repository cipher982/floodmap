"""
Clean FastAPI-only flood mapping application.
Single server architecture with clear separation of concerns.
"""

import logging
import os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

# Get logger
logger = logging.getLogger(__name__)

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

# Import middleware
from middleware.rate_limiter import RateLimitMiddleware
from routers import diagnostics as diagnostics_router
from routers import health, risk, tiles_performance_test, tiles_v1

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

# Serve static frontend files
app.mount("/static", StaticFiles(directory="../web"), name="static")


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main application frontend."""
    with open("../web/index.html") as f:
        return HTMLResponse(content=f.read())


@app.get("/favicon.svg", include_in_schema=False)
async def favicon_svg():
    """Serve the app's SVG favicon from the static web directory."""
    try:
        with open("../web/favicon.svg") as f:
            return Response(content=f.read(), media_type="image/svg+xml")
    except Exception:
        # Fallback to a simple emoji-based favicon if file missing
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
            "<text x='50%' y='50%' dominant-baseline='central' text-anchor='middle' font-size='52'>🌊</text>"
            "</svg>"
        )
        return Response(content=svg, media_type="image/svg+xml")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    """Redirect .ico requests to the SVG favicon to avoid 404s."""
    return RedirectResponse(url="/favicon.svg")


@app.get("/site.webmanifest", include_in_schema=False)
async def site_manifest():
    """Serve a minimal web app manifest for installability and theming."""
    manifest = {
        "name": "FloodMap USA",
        "short_name": "FloodMap",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0d47a1",
        "theme_color": "#0d47a1",
        # Use SVG so we don't require raster generation; modern browsers support this.
        "icons": [
            {
                "src": "/favicon.svg",
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


if __name__ == "__main__":
    import os

    # Get port from environment or use default
    port = int(os.getenv("API_PORT", "8000"))

    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True, log_level="info")
