"""
Clean FastAPI-only flood mapping application.
Single server architecture with clear separation of concerns.
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import uvicorn
import os
from dotenv import load_dotenv

# OpenTelemetry imports
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource

# Load environment variables from .env file
load_dotenv()

# Configure OpenTelemetry
def configure_telemetry():
    """Configure OpenTelemetry with ClickHouse backend."""
    # Only configure if ClickHouse connection details are provided
    otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not otel_endpoint:
        return
    
    resource = Resource.create({
        "service.name": "floodmap-api",
        "service.version": "2.0.0",
        "deployment.environment": os.getenv("ENVIRONMENT", "development")
    })
    
    trace.set_tracer_provider(TracerProvider(resource=resource))
    
    # Configure OTLP exporter for ClickHouse
    otlp_exporter = OTLPSpanExporter(
        endpoint=otel_endpoint,
        headers={
            "Authorization": f"Bearer {os.getenv('OTEL_EXPORTER_OTLP_HEADERS_AUTHORIZATION', '')}",
            **dict(h.split("=", 1) for h in os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "").split(",") if "=" in h)
        } if os.getenv("OTEL_EXPORTER_OTLP_HEADERS") else {}
    )
    
    span_processor = BatchSpanProcessor(otlp_exporter)
    trace.get_tracer_provider().add_span_processor(span_processor)

# Initialize telemetry
configure_telemetry()

# Import routers
from routers import tiles, tiles_v1, risk, health

# Import middleware
from middleware.rate_limiter import RateLimitMiddleware

# Create FastAPI app
app = FastAPI(
    title="Flood Risk Map API",
    description="Clean flood risk mapping service",
    version="2.0.0"
)

# Add middleware
app.add_middleware(RateLimitMiddleware, default_limit=60)

# Instrument FastAPI with OpenTelemetry
if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
    FastAPIInstrumentor.instrument_app(app)
    RequestsInstrumentor().instrument()

# Include API routers
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(tiles.router, prefix="/api", tags=["tiles"])  # Legacy routes
app.include_router(tiles_v1.router, tags=["tiles-v1"])  # New v1 routes (already prefixed)
app.include_router(risk.router, prefix="/api", tags=["risk"])

# Serve static frontend files
app.mount("/static", StaticFiles(directory="../web"), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main application frontend."""
    with open("../web/index.html", "r") as f:
        return HTMLResponse(content=f.read())

if __name__ == "__main__":
    import os
    
    # Get port from environment or use default
    port = int(os.getenv("API_PORT", "5002"))
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info"
    )