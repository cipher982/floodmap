"""
Clean FastAPI-only flood mapping application.
Single server architecture with clear separation of concerns.
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import uvicorn

# Import routers
from routers import tiles, risk, health

# Create FastAPI app
app = FastAPI(
    title="Flood Risk Map API",
    description="Clean flood risk mapping service",
    version="2.0.0"
)

# Include API routers
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(tiles.router, prefix="/api", tags=["tiles"])
app.include_router(risk.router, prefix="/api", tags=["risk"])

# Serve static frontend files
app.mount("/static", StaticFiles(directory="../web"), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main application frontend."""
    with open("../web/index.html", "r") as f:
        return HTMLResponse(content=f.read())

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5002,  # Use different port for new architecture
        reload=True,
        log_level="info"
    )