"""Tests for idempotency key derivation."""

from __future__ import annotations

from astraeus_trading.idempotency import derive_client_order_id


class TestIdempotency:
    """Unit tests for client_order_id derivation."""

    def test_deterministic(self) -> None:
        """Same inputs produce same output."""
        key1 = derive_client_order_id("strat1", "rec1", "dec1", 0)
        key2 = derive_client_order_id("strat1", "rec1", "dec1", 0)
        assert key1 == key2

    def test_different_strategy_different_key(self) -> None:
        key1 = derive_client_order_id("strat1", "rec1", "dec1", 0)
        key2 = derive_client_order_id("strat2", "rec1", "dec1", 0)
        assert key1 != key2

    def test_different_rec_different_key(self) -> None:
        key1 = derive_client_order_id("strat1", "rec1", "dec1", 0)
        key2 = derive_client_order_id("strat1", "rec2", "dec1", 0)
        assert key1 != key2

    def test_different_decision_different_key(self) -> None:
        key1 = derive_client_order_id("strat1", "rec1", "dec1", 0)
        key2 = derive_client_order_id("strat1", "rec1", "dec2", 0)
        assert key1 != key2

    def test_different_retry_different_key(self) -> None:
        key1 = derive_client_order_id("strat1", "rec1", "dec1", 0)
        key2 = derive_client_order_id("strat1", "rec1", "dec1", 1)
        assert key1 != key2

    def test_output_is_hex_sha256(self) -> None:
        key = derive_client_order_id("strat1", "rec1", "dec1", 0)
        assert len(key) == 64  # SHA-256 hex is 64 chars
        assert all(c in "0123456789abcdef" for c in key)
