"""
Secure rate limiting middleware with circuit breaker pattern.
Extracted from the legacy FastHTML implementation.
"""

import logging
import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

logger = logging.getLogger(__name__)


class RateLimitError(HTTPException):
    """Rate limit exceeded error."""

    def __init__(self, message: str, suggestions: list[str] = None):
        super().__init__(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "message": message,
                "suggestions": suggestions or [],
            },
        )


class RateLimiter:
    """Secure rate limiter with Redis backend and local fallback."""

    def __init__(self):
        self.redis_client: aioredis.Redis | None = None
        self.local_windows: dict[str, deque] = defaultdict(lambda: deque())
        self.redis_failures = 0
        self.last_redis_failure = 0
        self.circuit_breaker_threshold = 5
        self.circuit_breaker_timeout = 30

        # Initialize Redis if available
        redis_url = os.getenv("REDIS_URL")
        if redis_url and aioredis:
            try:
                self.redis_client = aioredis.from_url(redis_url, decode_responses=True)
                logger.info("Redis rate limiter initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Redis rate limiter: {e}")

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP with proper proxy support."""
        # Check for forwarded headers (in order of preference)
        forwarded_headers = [
            "cf-connecting-ip",  # Cloudflare
            "x-forwarded-for",  # Standard proxy header
            "x-real-ip",  # Nginx
            "x-client-ip",  # Alternative
        ]

        for header in forwarded_headers:
            if header in request.headers:
                # Handle comma-separated IPs (take first one)
                ip = request.headers[header].split(",")[0].strip()
                if ip and ip != "unknown":
                    return ip

        # Fallback to direct connection
        return str(request.client.host) if request.client else "unknown"

    def _is_redis_available(self) -> bool:
        """Check if Redis is available using circuit breaker pattern."""
        if not self.redis_client:
            return False

        now = time.time()

        # Circuit breaker: if too many recent failures, don't try Redis
        if (
            self.redis_failures >= self.circuit_breaker_threshold
            and now - self.last_redis_failure < self.circuit_breaker_timeout
        ):
            return False

        # Reset failure count after timeout
        if now - self.last_redis_failure > self.circuit_breaker_timeout:
            self.redis_failures = 0

        return True

    async def _redis_rate_limit(self, key: str, limit: int, window: int = 1) -> bool:
        """Redis-based rate limiting with sliding window."""
        try:
            pipe = self.redis_client.pipeline()
            now = time.time()
            window_start = now - window

            # Remove old entries
            pipe.zremrangebyscore(key, 0, window_start)
            # Add current request
            pipe.zadd(key, {str(now): now})
            # Count requests in window
            pipe.zcard(key)
            # Set expiry
            pipe.expire(key, window + 1)

            results = await pipe.execute()
            current_count = results[2]  # zcard result

            return current_count <= limit

        except Exception as e:
            self.redis_failures += 1
            self.last_redis_failure = time.time()
            logger.warning(f"Redis rate limit failed: {e}")
            raise

    async def _local_rate_limit(self, key: str, limit: int, window: int = 1) -> bool:
        """Local in-memory rate limiting fallback."""
        now = time.time()
        window_start = now - window

        # Clean old entries
        requests = self.local_windows[key]
        while requests and requests[0] < window_start:
            requests.popleft()

        # Check limit
        if len(requests) >= limit:
            return False

        # Add current request
        requests.append(now)
        return True

    async def check_rate_limit(
        self, request: Request, endpoint: str = "api", limit: int = 60
    ) -> None:
        """
        Check rate limit for a request.

        Args:
            request: FastAPI request object
            endpoint: Endpoint identifier for separate limits
            limit: Requests per second limit
        """
        client_ip = self._get_client_ip(request)
        key = f"rate_limit:{endpoint}:{client_ip}"

        try:
            # Try Redis first if available
            if self._is_redis_available():
                allowed = await self._redis_rate_limit(key, limit)
                if not allowed:
                    raise RateLimitError(
                        f"Rate limit exceeded for {endpoint}: {limit}/second",
                        suggestions=[
                            "Wait 1 second before retrying",
                            f"Reduce request frequency to max {limit}/second",
                        ],
                    )
                return

        except Exception as e:
            # Fall back to local rate limiting
            logger.warning(f"Redis rate limiting failed, using local fallback: {e}")

            # Apply stricter limits when Redis is failing
            fallback_limit = min(limit, 10)
            allowed = await self._local_rate_limit(key, fallback_limit)

            if not allowed:
                raise RateLimitError(
                    f"Rate limit exceeded (local fallback) for {endpoint}: {fallback_limit}/second",
                    suggestions=[
                        "Wait 1 second before retrying",
                        f"Reduce request frequency to max {fallback_limit}/second",
                    ],
                )


# Global rate limiter instance
rate_limiter = RateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for automatic rate limiting."""

    def __init__(self, app, default_limit: int = 60):
        super().__init__(app)
        self.default_limit = default_limit
        self.endpoint_limits = {
            "/api/v1/tiles/flood": 30,  # Flood tiles are expensive
            "/api/v1/tiles/elevation": 100,  # Elevation tiles are cached
            "/api/v1/tiles/vector": 100,  # Vector tiles are proxied
        }

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks
        if request.url.path in ["/api/health", "/health"]:
            return await call_next(request)

        # Determine rate limit for this endpoint
        limit = self.default_limit
        for pattern, endpoint_limit in self.endpoint_limits.items():
            if request.url.path.startswith(pattern):
                limit = endpoint_limit
                break

        # Apply rate limiting
        try:
            endpoint = (
                request.url.path.split("/")[1]
                if len(request.url.path.split("/")) > 1
                else "api"
            )
            await rate_limiter.check_rate_limit(request, endpoint, limit)
        except RateLimitError:
            raise

        return await call_next(request)
