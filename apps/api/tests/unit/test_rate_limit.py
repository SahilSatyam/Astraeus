"""Unit tests for rate limiting middleware.

Tests the in-memory rate limiter, the Redis-backed limiter (with a fake
client), and the per-env config loader.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from astraeus_api.rate_limit import (
    InMemoryRateLimiter,
    RateLimitConfig,
    RedisRateLimiter,
)


class TestInMemoryRateLimiter:
    """Test the in-memory sliding window rate limiter."""

    @pytest.mark.unit
    async def test_allows_within_limit(self):
        """Requests within limit are allowed."""
        limiter = InMemoryRateLimiter()
        for i in range(5):
            allowed, remaining = await limiter.is_allowed("test-key", limit=10)
            assert allowed is True
            assert remaining == 10 - i - 1

    @pytest.mark.unit
    async def test_blocks_over_limit(self):
        """Requests over limit are blocked."""
        limiter = InMemoryRateLimiter()
        for _ in range(5):
            await limiter.is_allowed("test-key", limit=5)

        allowed, remaining = await limiter.is_allowed("test-key", limit=5)
        assert allowed is False
        assert remaining == 0

    @pytest.mark.unit
    async def test_different_keys_independent(self):
        """Different keys have independent limits."""
        limiter = InMemoryRateLimiter()
        for _ in range(5):
            await limiter.is_allowed("key-a", limit=5)

        allowed, _ = await limiter.is_allowed("key-b", limit=5)
        assert allowed is True

    @pytest.mark.unit
    async def test_window_expiry(self):
        """Old requests expire from the window."""
        limiter = InMemoryRateLimiter()
        key = "expiry-test"
        limiter._windows[key] = [time.time() - 120]  # 2 minutes ago (expired)

        allowed, _ = await limiter.is_allowed(key, limit=1, window_seconds=60)
        assert allowed is True

    @pytest.mark.unit
    async def test_remaining_count_accurate(self):
        """Remaining count decreases correctly."""
        limiter = InMemoryRateLimiter()
        _, remaining = await limiter.is_allowed("count-test", limit=10)
        assert remaining == 9

        _, remaining = await limiter.is_allowed("count-test", limit=10)
        assert remaining == 8


class _FakeRedisPipeline:
    """Records pipeline operations and returns canned ZCARD results."""

    def __init__(self, parent: _FakeRedis) -> None:
        self._parent = parent
        self._ops: list[tuple[str, tuple[Any, ...]]] = []

    def zremrangebyscore(self, *args: Any) -> _FakeRedisPipeline:
        self._ops.append(("zremrangebyscore", args))
        return self

    def zadd(self, key: str, mapping: dict[str, int]) -> _FakeRedisPipeline:
        self._ops.append(("zadd", (key, mapping)))
        # Track per-key entries so zcard reflects reality.
        self._parent.entries.setdefault(key, []).extend(mapping.keys())
        return self

    def zcard(self, key: str) -> _FakeRedisPipeline:
        self._ops.append(("zcard", (key,)))
        return self

    def pexpire(self, *args: Any) -> _FakeRedisPipeline:
        self._ops.append(("pexpire", args))
        return self

    async def execute(self) -> list[Any]:
        # Build results in the order ops were appended.
        out: list[Any] = []
        for name, args in self._ops:
            if name == "zcard":
                out.append(len(self._parent.entries.get(args[0], [])))
            else:
                out.append(1)
        return out


class _FakeRedis:
    def __init__(self) -> None:
        self.entries: dict[str, list[str]] = {}

    def pipeline(self) -> _FakeRedisPipeline:
        return _FakeRedisPipeline(self)

    async def zrem(self, key: str, member: str) -> int:
        if member in self.entries.get(key, []):
            self.entries[key].remove(member)
            return 1
        return 0


class TestRedisRateLimiter:
    @pytest.mark.unit
    async def test_first_request_allowed(self) -> None:
        limiter = RedisRateLimiter(_FakeRedis())
        allowed, remaining = await limiter.is_allowed("k", limit=3)
        assert allowed is True
        assert remaining == 2

    @pytest.mark.unit
    async def test_blocks_when_over_limit(self) -> None:
        client = _FakeRedis()
        limiter = RedisRateLimiter(client)
        for _ in range(3):
            await limiter.is_allowed("k", limit=3)

        allowed, remaining = await limiter.is_allowed("k", limit=3)
        assert allowed is False
        assert remaining == 0
        # Rejected attempt should not inflate the window.
        assert len(client.entries["k"]) == 3

    @pytest.mark.unit
    async def test_redis_failure_fails_open(self) -> None:
        class BrokenRedis:
            def pipeline(self) -> Any:
                msg = "boom"
                raise RuntimeError(msg)

        limiter = RedisRateLimiter(BrokenRedis())
        allowed, remaining = await limiter.is_allowed("k", limit=3)
        assert allowed is True
        assert remaining == 3


class TestRateLimitConfig:
    @pytest.mark.unit
    def test_defaults_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in (
            "ASTRAEUS_RATE_LIMIT_GLOBAL",
            "ASTRAEUS_RATE_LIMIT_OMS_ORDERS",
            "ASTRAEUS_RATE_LIMIT_KILLSWITCH",
            "ASTRAEUS_RATE_LIMIT_AGENTS_RUNS",
            "ASTRAEUS_RATE_LIMIT_RECO_REPLAY",
            "ASTRAEUS_RATE_LIMIT_WINDOW_SECONDS",
        ):
            monkeypatch.delenv(var, raising=False)

        cfg = RateLimitConfig.from_env()
        assert cfg.global_limit == 300
        assert cfg.window_seconds == 60
        assert cfg.limits["/oms/orders"] == 60
        assert cfg.limits["/killswitch"] == 10

    @pytest.mark.unit
    def test_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ASTRAEUS_RATE_LIMIT_OMS_ORDERS", "5")
        monkeypatch.setenv("ASTRAEUS_RATE_LIMIT_GLOBAL", "1000")

        cfg = RateLimitConfig.from_env()
        assert cfg.limits["/oms/orders"] == 5
        assert cfg.global_limit == 1000

    @pytest.mark.unit
    def test_invalid_env_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ASTRAEUS_RATE_LIMIT_GLOBAL", "not-a-number")
        cfg = RateLimitConfig.from_env()
        assert cfg.global_limit == 300
