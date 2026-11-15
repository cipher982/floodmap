"""
Secure rate limiting middleware with circuit breaker pattern.
Extracted from the legacy FastHTML implementation.
"""

import ipaddress
import logging
import os
import time
from collections import OrderedDict, deque

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
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

    DEFAULT_MAX_LOCAL_WINDOWS = 10_000
    _TRUSTED_PROXY_NETWORKS = (
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("fe80::/10"),
    )

    def __init__(self, max_local_windows: int = DEFAULT_MAX_LOCAL_WINDOWS):
        self.redis_client: aioredis.Redis | None = None
        self.max_local_windows = max(1, max_local_windows)
        self.local_windows: OrderedDict[str, deque[float]] = OrderedDict()
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

    @staticmethod
    def _parse_ip(
        raw: str | None,
    ) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
        if not raw:
            return None
        candidate = raw.strip()
        if not candidate or candidate.lower() == "unknown":
            return None
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            return None
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            return ip.ipv4_mapped
        return ip

    @classmethod
    def _is_trusted_proxy_ip(cls, host: str) -> bool:
        ip = cls._parse_ip(host)
        if ip is None:
            return False
        return any(ip in net for net in cls._TRUSTED_PROXY_NETWORKS)

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, trusting forwarding headers only from private/loopback proxies."""
        peer_host = (
            str(request.client.host) if request.client and request.client.host else ""
        )
        if not peer_host:
            return "unknown"

        if self._is_trusted_proxy_ip(peer_host):
            cf_ip = self._parse_ip(request.headers.get("cf-connecting-ip"))
            if cf_ip is not None:
                return str(cf_ip)

            real_ip = self._parse_ip(request.headers.get("x-real-ip"))
            if real_ip is not None:
                return str(real_ip)

            xff = request.headers.get("x-forwarded-for", "")
            if xff:
                candidates = [p.strip() for p in xff.split(",") if p.strip()]
                fallback_ip = None
                for candidate in reversed(candidates):
                    parsed = self._parse_ip(candidate)
                    if parsed is None:
                        continue
                    if fallback_ip is None:
                        fallback_ip = str(parsed)
                    if not any(parsed in net for net in self._TRUSTED_PROXY_NETWORKS):
                        return str(parsed)
                if fallback_ip is not None:
                    return fallback_ip

        return peer_host

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

    def _prune_expired_windows(self, window_start: float) -> None:
        """Drop expired local windows to keep in-memory state bounded."""
        stale_keys = [
            k for k, dq in self.local_windows.items() if not dq or dq[-1] < window_start
        ]
        for k in stale_keys:
            self.local_windows.pop(k, None)

    async def _local_rate_limit(self, key: str, limit: int, window: int = 1) -> bool:
        """Local in-memory sliding-window rate limiting with bounded key table."""
        if limit <= 0:
            return False

        now = time.time()
        window_start = now - window

        requests = self.local_windows.get(key)
        if requests is not None:
            while requests and requests[0] < window_start:
                requests.popleft()
            self.local_windows.move_to_end(key)
        else:
            if len(self.local_windows) >= self.max_local_windows:
                self._prune_expired_windows(window_start)
            while len(self.local_windows) >= self.max_local_windows:
                self.local_windows.popitem(last=False)
            requests = deque()
            self.local_windows[key] = requests

        if len(requests) >= limit:
            return False

        requests.append(now)
        return True

    async def check_rate_limit(
        self, request: Request, endpoint: str = "api", limit: int = 30
    ) -> None:
        """
        Check rate limit for a request.

        Args:
            request: FastAPI request object
            endpoint: Endpoint category identifier for separate buckets
            limit: Requests per second limit
        """
        client_ip = self._get_client_ip(request)
        key = f"rate_limit:{endpoint}:{client_ip}"

        allowed = True
        if self._is_redis_available():
            try:
                allowed = await self._redis_rate_limit(key, limit)
            except RateLimitError:
                raise
            except Exception as e:
                logger.warning(f"Redis rate limiting failed, using local fallback: {e}")
                allowed = await self._local_rate_limit(key, limit)
        else:
            allowed = await self._local_rate_limit(key, limit)

        if not allowed:
            raise RateLimitError(
                f"Rate limit exceeded for {endpoint}: {limit}/second",
                suggestions=[
                    "Wait 1 second before retrying",
                    f"Reduce request frequency to max {limit}/second",
                ],
            )


# Global rate limiter instance
rate_limiter = RateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for automatic rate limiting by route category."""

    def __init__(
        self,
        app,
        default_limit: int = 30,
        tiles_limit: int = 200,
        places_limit: int = 5,
    ):
        super().__init__(app)
        self.default_limit = default_limit
        self.tiles_limit = tiles_limit
        self.places_limit = places_limit

    @staticmethod
    def _normalize_path(path: str) -> str:
        if path == "/floodmap":
            return "/"
        if path.startswith("/floodmap/"):
            return path[len("/floodmap") :]
        return path

    def _classify_request(self, path: str) -> tuple[str, int]:
        norm_path = self._normalize_path(path)
        if norm_path == "/api/places" or norm_path.startswith("/api/places/"):
            return "places", self.places_limit
        if norm_path.startswith("/api/v1/tiles/") or (
            norm_path.startswith("/api/v2/terrain/")
            and not norm_path.endswith("/sample")
        ):
            return "tiles", self.tiles_limit
        if norm_path.startswith("/static/"):
            return "static", max(self.default_limit, 60)
        return "api", self.default_limit

    async def dispatch(self, request: Request, call_next):
        norm_path = self._normalize_path(request.url.path)
        if norm_path in {"/api/health", "/health", "/api/v1/tiles/health"}:
            return await call_next(request)

        bucket, limit = self._classify_request(request.url.path)

        try:
            await rate_limiter.check_rate_limit(request, bucket, limit)
        except RateLimitError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers={"Retry-After": "1"},
            )

        return await call_next(request)
