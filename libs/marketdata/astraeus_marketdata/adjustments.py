"""Corporate action adjustment worker.

Applies splits and dividends to raw bars, producing adjusted bars.
The adjustment is idempotent: re-running with the same actions produces
identical output (verified via adjustment_hash).

Adjusted bars are stored in market_bars_adjusted as a separate table
(not a flag column) to prevent accidental re-adjustment bugs.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import delete, select

from astraeus_marketdata.models import CorporateAction, MarketBarAdjusted, MarketBarRaw

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("astraeus.marketdata.adjustments")


def _compute_adjustment_hash(actions: list[CorporateAction]) -> bytes:
    """Deterministic hash of the action set used for adjustment.

    If the same actions produce the same hash, the adjusted output is identical.
    """
    canonical = json.dumps(
        [
            {
                "symbol": a.symbol,
                "action_type": a.action_type,
                "ex_date": a.ex_date.isoformat(),
                "ratio": str(a.ratio) if a.ratio else None,
                "cash_amount": str(a.cash_amount) if a.cash_amount else None,
            }
            for a in sorted(actions, key=lambda x: (x.symbol, x.ex_date))
        ],
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).digest()


def _apply_split(price: Decimal, ratio: Decimal) -> Decimal:
    """Apply a split ratio to a price. E.g., 7:1 split → divide by 7."""
    if ratio == 0:
        return price
    return (price / ratio).quantize(Decimal("0.00000001"))


def _apply_dividend(price: Decimal, cumulative_dividend: Decimal) -> Decimal:
    """Apply cumulative dividend adjustment to a price.

    Uses the proportional method: adjusted = price - cumulative_dividend
    This is the standard approach for back-adjusting historical prices.
    """
    adjusted = price - cumulative_dividend
    if adjusted <= 0:
        return price  # Safety: never produce negative prices
    return adjusted.quantize(Decimal("0.00000001"))


async def adjust_symbol(
    session: AsyncSession,
    symbol: str,
    source: str | None = None,
) -> int:
    """Rebuild adjusted bars for a symbol from raw bars + corporate actions.

    This is a full rebuild: deletes existing adjusted bars for the symbol
    and recomputes from scratch. Idempotent by design.

    Returns:
        Number of adjusted bars written.
    """
    # Fetch all corporate actions for this symbol
    actions_query = select(CorporateAction).where(CorporateAction.symbol == symbol)
    if source:
        actions_query = actions_query.where(CorporateAction.source == source)
    actions_query = actions_query.order_by(CorporateAction.ex_date)

    result = await session.execute(actions_query)
    actions = list(result.scalars().all())

    adjustment_hash = _compute_adjustment_hash(actions)

    # Fetch raw bars
    raw_query = select(MarketBarRaw).where(MarketBarRaw.symbol == symbol).order_by(MarketBarRaw.ts)
    raw_result = await session.execute(raw_query)
    raw_bars = list(raw_result.scalars().all())

    if not raw_bars:
        return 0

    # Delete existing adjusted bars for this symbol
    await session.execute(delete(MarketBarAdjusted).where(MarketBarAdjusted.symbol == symbol))

    # Build split schedule: for each date, cumulative split factor
    # Splits apply to all bars BEFORE the ex_date
    splits = [a for a in actions if a.action_type == "split" and a.ratio]
    dividends = [a for a in actions if a.action_type == "dividend" and a.cash_amount]

    now = datetime.now(tz=UTC)
    written = 0

    for raw_bar in raw_bars:
        # Calculate cumulative split factor for this bar's date
        cumulative_ratio = Decimal("1")
        cumulative_dividend = Decimal("0")
        bar_date = raw_bar.ts.date() if isinstance(raw_bar.ts, datetime) else raw_bar.ts

        for split in splits:
            if bar_date < split.ex_date:
                cumulative_ratio *= split.ratio  # type: ignore[operator]

        # Calculate cumulative dividend adjustment
        # Dividends reduce historical prices for bars BEFORE the ex_date
        for div in dividends:
            if bar_date < div.ex_date:
                # Adjust dividend amount for any splits that happened between
                # the bar date and the dividend ex_date
                div_adjustment = div.cash_amount  # type: ignore[assignment]
                for split in splits:
                    if bar_date < split.ex_date <= div.ex_date:
                        div_adjustment = div_adjustment / split.ratio  # type: ignore[operator]
                cumulative_dividend += div_adjustment

        # Apply split adjustment first, then dividend
        adj_open = _apply_split(raw_bar.open, cumulative_ratio)
        adj_high = _apply_split(raw_bar.high, cumulative_ratio)
        adj_low = _apply_split(raw_bar.low, cumulative_ratio)
        adj_close = _apply_split(raw_bar.close, cumulative_ratio)

        # Apply dividend adjustment
        if cumulative_dividend > 0:
            adj_open = _apply_dividend(adj_open, cumulative_dividend)
            adj_high = _apply_dividend(adj_high, cumulative_dividend)
            adj_low = _apply_dividend(adj_low, cumulative_dividend)
            adj_close = _apply_dividend(adj_close, cumulative_dividend)

        adj_volume = int(raw_bar.volume * cumulative_ratio) if raw_bar.volume else None

        adj_bar = MarketBarAdjusted(
            symbol=raw_bar.symbol,
            ts=raw_bar.ts,
            resolution=raw_bar.resolution,
            open=adj_open,
            high=adj_high,
            low=adj_low,
            close=adj_close,
            volume=adj_volume,
            vwap=raw_bar.vwap,
            trades=raw_bar.trades,
            source=raw_bar.source,
            schema_version=raw_bar.schema_version,
            ingest_run_id=raw_bar.ingest_run_id,
            payload_hash=raw_bar.payload_hash,
            adjusted_at=now,
            adjustment_hash=adjustment_hash,
        )
        session.add(adj_bar)
        written += 1

    await session.flush()

    logger.info(
        "adjustment_complete",
        symbol=symbol,
        raw_bars=len(raw_bars),
        actions=len(actions),
        adjusted_bars=written,
    )

    return written
