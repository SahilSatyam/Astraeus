"""Rate limiting middleware backed by Redis (with in-memory fallback).

Protects against accidental order floods and API abuse. Per-route limits are
configurable via :class:`RateLimitConfig` (see env vars below); writes go
through Redis so multiple API replicas share state.

Env vars (all optional):

- ``ASTRAEUS_RATE_LIMIT_REDIS_URL`` — full Redis URL. If unset, falls back to
  the (per-pod) in-memory limiter, which is suitable only for single-replica
  deployments and dev.
- ``ASTRAEUS_RATE_LIMIT_GLOBAL`` — global default rpm (default: 300).
- ``ASTRAEUS_RATE_LIMIT_OMS_ORDERS`` — POST/PUT to /oms/orders (default: 60).
- ``ASTRAEUS_RATE_LIMIT_KILLSWITCH`` — kill switch (default: 10).
- ``ASTRAEUS_RATE_LIMIT_AGENTS_RUNS`` — agent runs (default: 20).
- ``ASTRAEUS_RATE_LIMIT_RECO_REPLAY`` — pipeline replay (default: 5).
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.middleware.base import RequestResponseEndpoint
    from starlette.requests import Request
    from starlette.responses import Response

logger = structlog.get_logger("astraeus.api.rate_limit")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("rate_limit_invalid_env", name=name, value=raw, fallback=default)
        return default


@dataclass(frozen=True)
class RateLimitConfig:
    """Per-route rate-limit configuration loaded from env.

    ``limits`` maps a path *prefix* to its rpm cap. The first matching prefix
    wins; if none match, ``global_limit`` applies.
    """

    global_limit: int = 300
    window_seconds: int = 60
    limits: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> RateLimitConfig:
        return cls(
            global_limit=_env_int("ASTRAEUS_RATE_LIMIT_GLOBAL", 300),
            window_seconds=_env_int("ASTRAEUS_RATE_LIMIT_WINDOW_SECONDS", 60),
            limits={
                "/oms/orders": _env_int("ASTRAEUS_RATE_LIMIT_OMS_ORDERS", 60),
                "/killswitch": _env_int("ASTRAEUS_RATE_LIMIT_KILLSWITCH", 10),
                "/agents/runs": _env_int("ASTRAEUS_RATE_LIMIT_AGENTS_RUNS", 20),
                "/reco/replay": _env_int("ASTRAEUS_RATE_LIMIT_RECO_REPLAY", 5),
            },
        )


class _Limiter(Protocol):
    async def is_allowed(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]: ...


class InMemoryRateLimiter:
    """Simple in-memory sliding window rate limiter.

    Used as fallback when Redis is unavailable. Not suitable for
    multi-instance deployments (use Redis-backed limiter instead).
    """

    def __init__(self) -> None:
        self._windows: dict[str, list[float]] = defaultdict(list)

    async def is_allowed(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
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


class RedisRateLimiter:
    """Sliding-window rate limiter backed by Redis sorted sets.

    Uses ZADD/ZREMRANGEBYSCORE/ZCARD inside a pipeline so the read+write is
    atomic per key. Each key TTLs after the window so we don't accumulate
    state for cold paths.
    """

    def __init__(self, redis_client: object) -> None:
        # ``redis.asyncio.Redis`` — typed loosely to avoid hard import in tests.
        self._redis = redis_client

    async def is_allowed(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        now_ms = int(time.time() * 1000)
        window_ms = window_seconds * 1000
        cutoff = now_ms - window_ms
        member = f"{now_ms}-{os.urandom(4).hex()}"

        try:
            pipe = self._redis.pipeline()  # type: ignore[attr-defined]
            pipe.zremrangebyscore(key, 0, cutoff)
            pipe.zadd(key, {member: now_ms})
            pipe.zcard(key)
            pipe.pexpire(key, window_ms)
            results = await pipe.execute()
            count = int(results[2])
        except Exception as exc:
            # Network/Redis failures must not take the API down. Log loudly,
            # fail-open so legitimate traffic continues.
            logger.warning("rate_limit_redis_error", error=str(exc), key=key)
            return True, limit

        if count > limit:
            # Pop the entry we just added so a future request in the same
            # window has its real count, not inflated by rejected attempts.
            try:
                await self._redis.zrem(key, member)  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover — best-effort cleanup
                pass
            return False, 0
        return True, max(limit - count, 0)


def _build_limiter() -> _Limiter:
    """Choose Redis-backed limiter when configured, otherwise in-memory."""
    redis_url = os.environ.get("ASTRAEUS_RATE_LIMIT_REDIS_URL", "").strip()
    if not redis_url:
        return InMemoryRateLimiter()
    try:
        from redis.asyncio import from_url

        client = from_url(redis_url, decode_responses=False)
    except Exception as exc:
        logger.warning(
            "rate_limit_redis_init_failed",
            error=str(exc),
            fallback="in-memory",
        )
        return InMemoryRateLimiter()
    logger.info("rate_limit_redis_enabled", url=redis_url)
    return RedisRateLimiter(client)


_SKIP_PATHS = frozenset({"/healthz", "/readyz", "/metrics", "/version"})
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware with per-route limits.

    Picks Redis-backed storage when ``ASTRAEUS_RATE_LIMIT_REDIS_URL`` is set,
    otherwise falls back to per-process in-memory state.
    """

    def __init__(
        self,
        app: object,
        config: RateLimitConfig | None = None,
        limiter: _Limiter | None = None,
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._config = config or RateLimitConfig.from_env()
        self._limiter = limiter or _build_limiter()

    def _client_ip(self, request: Request) -> str:
        # ProxyHeadersMiddleware (added in app.py) updates request.client.host
        # to the X-Forwarded-For value when the connection comes from a
        # trusted proxy, so this is the real client IP in prod.
        return request.client.host if request.client else "unknown"

    def _limit_for(self, path: str) -> int:
        for prefix, route_limit in self._config.limits.items():
            if path.startswith(prefix):
                return route_limit
        return self._config.global_limit

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path in _SKIP_PATHS or request.method not in _MUTATING_METHODS:
            return await call_next(request)

        limit = self._limit_for(path)
        # Bucket per (client, top-level path segment) so /oms/orders/{id}
        # and /oms/orders share the same limiter key.
        first_segment = path.split("/", 2)[1] if path.startswith("/") and len(path) > 1 else path
        key = f"ratelimit:{self._client_ip(request)}:{first_segment}"

        allowed, remaining = await self._limiter.is_allowed(key, limit, self._config.window_seconds)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "retry_after_seconds": self._config.window_seconds,
                },
                headers={
                    "Retry-After": str(self._config.window_seconds),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


# Backwards-compatible aliases for callers that imported the prior names.
DEFAULT_LIMITS = RateLimitConfig.from_env().limits
GLOBAL_LIMIT_PER_MINUTE = RateLimitConfig.from_env().global_limit
