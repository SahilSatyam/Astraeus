"""Unit tests for base adapter utilities."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from astraeus_marketdata.adapters.base import BarRecord, compute_payload_hash


@pytest.mark.unit
def test_payload_hash_deterministic() -> None:
    """Same bar + source should always produce the same hash."""
    bar = BarRecord(
        symbol="SPY",
        ts=datetime(2024, 1, 2, tzinfo=timezone.utc),
        resolution="1d",
        open=Decimal("470.50"),
        high=Decimal("472.00"),
        low=Decimal("469.00"),
        close=Decimal("471.25"),
        volume=50000000,
    )
    h1 = compute_payload_hash(bar, "yahoo")
    h2 = compute_payload_hash(bar, "yahoo")
    assert h1 == h2
    assert len(h1) == 32  # SHA-256


@pytest.mark.unit
def test_payload_hash_differs_by_source() -> None:
    """Different source should produce different hash (lineage isolation)."""
    bar = BarRecord(
        symbol="SPY",
        ts=datetime(2024, 1, 2, tzinfo=timezone.utc),
        resolution="1d",
        open=Decimal("470.50"),
        high=Decimal("472.00"),
        low=Decimal("469.00"),
        close=Decimal("471.25"),
    )
    h_yahoo = compute_payload_hash(bar, "yahoo")
    h_alpaca = compute_payload_hash(bar, "alpaca")
    assert h_yahoo != h_alpaca


@pytest.mark.unit
def test_payload_hash_differs_by_data() -> None:
    """Different price should produce different hash."""
    bar1 = BarRecord(
        symbol="SPY",
        ts=datetime(2024, 1, 2, tzinfo=timezone.utc),
        resolution="1d",
        open=Decimal("470.50"),
        high=Decimal("472.00"),
        low=Decimal("469.00"),
        close=Decimal("471.25"),
    )
    bar2 = BarRecord(
        symbol="SPY",
        ts=datetime(2024, 1, 2, tzinfo=timezone.utc),
        resolution="1d",
        open=Decimal("470.51"),  # different
        high=Decimal("472.00"),
        low=Decimal("469.00"),
        close=Decimal("471.25"),
    )
    assert compute_payload_hash(bar1, "yahoo") != compute_payload_hash(bar2, "yahoo")
