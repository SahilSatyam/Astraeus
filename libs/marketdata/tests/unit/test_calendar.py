"""Unit tests for the market calendar service."""

from __future__ import annotations

from datetime import date

import pytest

from astraeus_marketdata.calendar import get_trading_days, is_trading_day


@pytest.mark.unit
def test_christmas_not_trading_day() -> None:
    """Christmas Day should not be a trading day on NYSE."""
    assert not is_trading_day("NYSE", date(2024, 12, 25))


@pytest.mark.unit
def test_regular_weekday_is_trading_day() -> None:
    """A regular Monday should be a trading day."""
    # Dec 2, 2024 is a Monday
    assert is_trading_day("NYSE", date(2024, 12, 2))


@pytest.mark.unit
def test_weekend_not_trading_day() -> None:
    """Weekends should not be trading days."""
    # Dec 7, 2024 is a Saturday
    assert not is_trading_day("NYSE", date(2024, 12, 7))


@pytest.mark.unit
def test_trading_days_excludes_holidays() -> None:
    """Trading days for a holiday week should exclude the holiday."""
    days = get_trading_days("NYSE", date(2024, 12, 23), date(2024, 12, 27))
    # Dec 25 is Christmas
    assert date(2024, 12, 25) not in days
    assert date(2024, 12, 23) in days
    assert date(2024, 12, 24) in days
    assert date(2024, 12, 26) in days
    assert date(2024, 12, 27) in days


@pytest.mark.unit
def test_nasdaq_same_holidays_as_nyse() -> None:
    """NASDAQ follows the same holiday schedule as NYSE."""
    assert not is_trading_day("NASDAQ", date(2024, 12, 25))
    assert is_trading_day("NASDAQ", date(2024, 12, 26))
