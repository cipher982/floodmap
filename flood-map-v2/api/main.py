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

# Load environment variables from .env file
load_dotenv()

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