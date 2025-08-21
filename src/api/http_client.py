"""
Shared HTTP client for efficient connection pooling.
Handles burst tile requests without connection exhaustion.
"""

import httpx
import asyncio
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class SharedHTTPClient:
    """
    Singleton HTTP client optimized for tile server requests.
    
    Designed to handle burst requests (50-100 simultaneous tiles during map drag)
    without connection pool exhaustion.
    """
    
    _instance: Optional['SharedHTTPClient'] = None
    _client: Optional[httpx.AsyncClient] = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def get_client(self) -> httpx.AsyncClient:
        """Get the shared HTTP client, creating it if necessary."""
        if self._client is None:
            async with self._lock:
                if self._client is None:  # Double-check pattern
                    self._client = self._create_client()
                    logger.info("🔗 Created shared HTTP client for tile requests")
        return self._client
    
    def _create_client(self) -> httpx.AsyncClient:
        """Create HTTP client optimized for tile server connections."""
        
        # Simplified connection limits for debugging
        limits = httpx.Limits(
            max_connections=100,          # Reduced for debugging
            max_keepalive_connections=20, # Reduced for debugging
        )
        
        # Increased timeout for debugging
        timeout = httpx.Timeout(30.0)  # Simple 30 second timeout
        
        return httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
            follow_redirects=False,  # Direct tile server communication
            # http2=True,           # Disabled - requires 'h2' package
        )
    
    async def close(self):
        """Close the shared HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("🔒 Closed shared HTTP client")


# Global instance for easy access
_shared_client = SharedHTTPClient()


async def get_http_client() -> httpx.AsyncClient:
    """
    Get the shared HTTP client instance.
    
    This client is optimized for handling burst tile requests
    without connection pool exhaustion.
    """
    return await _shared_client.get_client()


async def close_http_client():
    """Close the shared HTTP client (for shutdown)."""
    await _shared_client.close()