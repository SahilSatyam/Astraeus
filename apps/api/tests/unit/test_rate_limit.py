"""Unit tests for rate limiting middleware.

Tests the in-memory rate limiter and middleware behavior.
"""

from __future__ import annotations

import time

import pytest
from astraeus_api.rate_limit import InMemoryRateLimiter


class TestInMemoryRateLimiter:
    """Test the in-memory sliding window rate limiter."""

    @pytest.mark.unit
    def test_allows_within_limit(self):
        """Requests within limit are allowed."""
        limiter = InMemoryRateLimiter()
        for i in range(5):
            allowed, remaining = limiter.is_allowed("test-key", limit=10)
            assert allowed is True
            assert remaining == 10 - i - 1

    @pytest.mark.unit
    def test_blocks_over_limit(self):
        """Requests over limit are blocked."""
        limiter = InMemoryRateLimiter()
        # Fill up the limit
        for _ in range(5):
            limiter.is_allowed("test-key", limit=5)

        # Next request should be blocked
        allowed, remaining = limiter.is_allowed("test-key", limit=5)
        assert allowed is False
        assert remaining == 0

    @pytest.mark.unit
    def test_different_keys_independent(self):
        """Different keys have independent limits."""
        limiter = InMemoryRateLimiter()
        # Fill key A
        for _ in range(5):
            limiter.is_allowed("key-a", limit=5)

        # Key B should still be allowed
        allowed, _ = limiter.is_allowed("key-b", limit=5)
        assert allowed is True

    @pytest.mark.unit
    def test_window_expiry(self):
        """Old requests expire from the window."""
        limiter = InMemoryRateLimiter()

        # Add requests with timestamps in the past
        key = "expiry-test"
        limiter._windows[key] = [time.time() - 120]  # 2 minutes ago (expired)

        # Should be allowed (old request expired)
        allowed, _ = limiter.is_allowed(key, limit=1, window_seconds=60)
        assert allowed is True

    @pytest.mark.unit
    def test_remaining_count_accurate(self):
        """Remaining count decreases correctly."""
        limiter = InMemoryRateLimiter()
        _, remaining = limiter.is_allowed("count-test", limit=10)
        assert remaining == 9

        _, remaining = limiter.is_allowed("count-test", limit=10)
        assert remaining == 8
