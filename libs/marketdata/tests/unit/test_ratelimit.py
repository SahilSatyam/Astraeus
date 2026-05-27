"""Unit tests for the token-bucket rate limiter."""

from __future__ import annotations

import asyncio
import time

import pytest

from astraeus_marketdata.ratelimit import RateLimiter


@pytest.mark.unit
async def test_rate_limiter_allows_burst() -> None:
    """Should allow up to `rate` requests immediately."""
    limiter = RateLimiter(rate=5, period=1.0)
    start = time.monotonic()
    for _ in range(5):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    # All 5 should complete nearly instantly
    assert elapsed < 0.1


@pytest.mark.unit
async def test_rate_limiter_throttles_after_burst() -> None:
    """Should throttle after burst is exhausted."""
    limiter = RateLimiter(rate=3, period=1.0)
    # Exhaust burst
    for _ in range(3):
        await limiter.acquire()
    # Next acquire should wait
    start = time.monotonic()
    await limiter.acquire()
    elapsed = time.monotonic() - start
    # Should have waited ~0.33s (1 token refills in period/rate = 1/3 s)
    assert elapsed >= 0.2
