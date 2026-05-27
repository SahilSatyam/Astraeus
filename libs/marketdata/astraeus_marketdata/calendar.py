"""Market calendar service.

Wraps pandas-market-calendars to provide trading day schedules for
gap detection and backfill planning. All timestamps are UTC.

Supported exchanges: NYSE, NASDAQ, CME, LSE.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from functools import lru_cache

import exchange_calendars as xcals
import structlog

logger = structlog.get_logger("astraeus.marketdata.calendar")


# Exchange code mapping
_EXCHANGE_MAP = {
    "NYSE": "XNYS",
    "NASDAQ": "XNAS",
    "CME": "XCME",
    "LSE": "XLON",
}


@lru_cache(maxsize=8)
def _get_calendar(exchange: str) -> xcals.ExchangeCalendar:
    """Get (cached) exchange calendar instance."""
    code = _EXCHANGE_MAP.get(exchange.upper(), exchange)
    return xcals.get_calendar(code)


def get_trading_days(
    exchange: str,
    start: date,
    end: date,
) -> list[date]:
    """Return all trading days for the given exchange and date range.

    Args:
        exchange: Exchange code (NYSE, NASDAQ, CME, LSE).
        start: Start date (inclusive).
        end: End date (inclusive).

    Returns:
        Sorted list of trading dates.
    """
    cal = _get_calendar(exchange)
    sessions = cal.sessions_in_range(
        start.isoformat(),
        end.isoformat(),
    )
    return [s.date() for s in sessions]


def is_trading_day(exchange: str, check_date: date) -> bool:
    """Check if a specific date is a trading day."""
    cal = _get_calendar(exchange)
    return cal.is_session(check_date.isoformat())


def get_next_trading_day(exchange: str, after: date) -> date:
    """Get the next trading day after the given date."""
    cal = _get_calendar(exchange)
    # Find next session
    ts = cal.next_session(after.isoformat())
    return ts.date()


def get_market_open_close(
    exchange: str,
    trading_date: date,
) -> tuple[datetime, datetime] | None:
    """Get market open and close times in UTC for a trading day.

    Returns None if the date is not a trading day.
    """
    cal = _get_calendar(exchange)
    if not cal.is_session(trading_date.isoformat()):
        return None

    open_time = cal.session_open(trading_date.isoformat())
    close_time = cal.session_close(trading_date.isoformat())

    return (
        open_time.to_pydatetime().replace(tzinfo=timezone.utc),
        close_time.to_pydatetime().replace(tzinfo=timezone.utc),
    )


async def get_trading_days_async(
    exchange: str,
    start: date,
    end: date,
) -> list[date]:
    """Async wrapper for get_trading_days (runs in executor)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, get_trading_days, exchange, start, end)
