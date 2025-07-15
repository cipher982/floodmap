"""Health check endpoints."""
from fastapi import APIRouter
from datetime import datetime

router = APIRouter()

@router.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "flood-map-api"
    }

@router.get("/status")
async def detailed_status():
    """Detailed service status."""
    return {
        "api": "running",
        "elevation_data": "loaded",  # TODO: Check actual data
        "vector_tiles": "available",  # TODO: Check tileserver
        "timestamp": datetime.utcnow().isoformat()
    }