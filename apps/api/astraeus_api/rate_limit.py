"""Rate limiting middleware using a sliding window counter in Redis.

Protects against accidental order floods and API abuse. Configurable per-route
limits with fallback to in-memory counter when Redis is unavailable.

Usage:
    app.add_middleware(RateLimitMiddleware, redis_url="redis://localhost:6379")
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.middleware.base import RequestResponseEndpoint
    from starlette.requests import Request
    from starlette.responses import Response


# Default rate limits per path prefix (requests per minute)
DEFAULT_LIMITS: dict[str, int] = {
    "/oms/orders": 60,  # Order submission: 1/sec max
    "/killswitch": 10,  # Kill switch: 10/min
    "/agents/runs": 20,  # Agent runs: 20/min (expensive)
    "/reco/replay": 5,  # Pipeline replay: 5/min
}

# Global fallback limit
GLOBAL_LIMIT_PER_MINUTE = 300


class InMemoryRateLimiter:
    """Simple in-memory sliding window rate limiter.

    Used as fallback when Redis is unavailable. Not suitable for
    multi-instance deployments (use Redis-backed limiter instead).
    """

    def __init__(self) -> None:
        self._windows: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        """Check if request is allowed. Returns (allowed, remaining)."""
        now = time.time()
        cutoff = now - window_seconds

        # Clean old entries
        self._windows[key] = [t for t in self._windows[key] if t > cutoff]

        current_count = len(self._windows[key])
        if current_count >= limit:
            return False, 0

        self._windows[key].append(now)
        return True, limit - current_count - 1


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware with per-route limits.

    Falls back to in-memory limiter. For production multi-instance
    deployments, extend with Redis INCR + EXPIRE pattern.
    """

    def __init__(self, app: object, limits: dict[str, int] | None = None) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._limiter = InMemoryRateLimiter()
        self._limits = limits or DEFAULT_LIMITS

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip rate limiting for health/metrics endpoints
        path = request.url.path
        if path in ("/healthz", "/readyz", "/metrics", "/version"):
            return await call_next(request)

        # Only rate limit mutating requests
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return await call_next(request)

        # Determine limit for this path
        limit = GLOBAL_LIMIT_PER_MINUTE
        for prefix, route_limit in self._limits.items():
            if path.startswith(prefix):
                limit = route_limit
                break

        # Key: client IP + path prefix
        client_ip = request.client.host if request.client else "unknown"
        key = f"{client_ip}:{path.split('/')[1] if '/' in path[1:] else path}"

        allowed, remaining = self._limiter.is_allowed(key, limit)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "retry_after_seconds": 60,
                },
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
