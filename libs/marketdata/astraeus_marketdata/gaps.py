"""Gap detector — compares expected trading days vs actual data.

Runs nightly (or on-demand) to identify missing data points. Gaps are
materialised in the data_gaps table so they're queryable and trackable.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import func, select

from astraeus_marketdata.calendar import get_trading_days
from astraeus_marketdata.models import DataGap, MarketBarRaw

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("astraeus.marketdata.gaps")


async def detect_gaps(
    session: AsyncSession,
    symbols: list[str],
    exchange: str,
    start: date,
    end: date,
    resolution: str = "1d",
) -> list[DataGap]:
    """Detect missing bars by comparing calendar expectations vs actual data.

    For each symbol, checks which expected trading days have no bar in
    market_bars_raw. Creates DataGap entries for any missing dates.

    Returns:
        List of newly created DataGap entries.
    """
    expected_days = get_trading_days(exchange, start, end)
    new_gaps: list[DataGap] = []

    for symbol in symbols:
        # Get all dates we have data for
        result = await session.execute(
            select(func.date_trunc("day", MarketBarRaw.ts))
            .where(
                MarketBarRaw.symbol == symbol,
                MarketBarRaw.resolution == resolution,
                MarketBarRaw.ts >= datetime(start.year, start.month, start.day, tzinfo=UTC),
                MarketBarRaw.ts <= datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC),
            )
            .distinct()
        )
        actual_dates = {row[0].date() for row in result.all()}

        # Find missing days
        missing = set(expected_days) - actual_dates

        for missing_date in sorted(missing):
            # Check if gap already recorded
            existing = await session.execute(
                select(DataGap.id).where(
                    DataGap.symbol == symbol,
                    DataGap.resolution == resolution,
                    DataGap.expected_ts
                    == datetime(
                        missing_date.year,
                        missing_date.month,
                        missing_date.day,
                        tzinfo=UTC,
                    ),
                )
            )
            if existing.scalar_one_or_none() is not None:
                continue

            gap = DataGap(
                symbol=symbol,
                resolution=resolution,
                expected_ts=datetime(
                    missing_date.year,
                    missing_date.month,
                    missing_date.day,
                    tzinfo=UTC,
                ),
            )
            session.add(gap)
            new_gaps.append(gap)

    if new_gaps:
        await session.flush()
        logger.warning(
            "gaps_detected",
            count=len(new_gaps),
            symbols=len(symbols),
            exchange=exchange,
        )
    else:
        logger.info("no_gaps_detected", symbols=len(symbols), exchange=exchange)

    return new_gaps


async def resolve_gap(
    session: AsyncSession,
    symbol: str,
    resolution: str,
    expected_ts: datetime,
) -> None:
    """Mark a gap as resolved (data has been backfilled)."""
    result = await session.execute(
        select(DataGap).where(
            DataGap.symbol == symbol,
            DataGap.resolution == resolution,
            DataGap.expected_ts == expected_ts,
            DataGap.resolved_at.is_(None),
        )
    )
    gap = result.scalar_one_or_none()
    if gap:
        gap.resolved_at = datetime.now(tz=UTC)
        await session.flush()
