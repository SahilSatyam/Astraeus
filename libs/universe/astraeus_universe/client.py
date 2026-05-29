"""Universe client — survivorship-bias-aware membership queries.

This is the only sanctioned way to query universe membership.
All queries are PIT-correct: they respect both the effective period
and the knowledge timestamp.

Usage:
    from astraeus_universe import universe

    # Get S&P 500 members as of a specific date
    members = await universe.members("sp500", as_of_ts=datetime(2020, 6, 30, tzinfo=UTC))

    # Get members over a window (for backfills)
    all_members = await universe.members_over_window("sp500", start, end)

    # Resolve a ticker to canonical symbol
    canonical = await universe.resolve("META", alias_type="ticker", as_of_ts=dt)
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import or_, select

from astraeus_universe.models import SecurityAlias, SecurityMaster, UniverseMembership

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("astraeus.universe")


async def members(
    session: AsyncSession,
    universe_id: str,
    as_of_ts: datetime,
) -> list[str]:
    """Get universe members as of a specific point in time.

    This is the core survivorship-bias-aware query. It returns only symbols
    that were members of the universe at `as_of_ts`, considering both:
    - The effective membership period (effective_from <= as_of < effective_to)
    - The knowledge timestamp (we knew about the membership by as_of_ts)

    Args:
        session: Database session.
        universe_id: Universe identifier (e.g., "sp500", "russell2000").
        as_of_ts: Point-in-time for the query (must be tz-aware UTC).

    Returns:
        Sorted list of canonical symbol strings.
    """
    if as_of_ts.tzinfo is None:
        raise ValueError("as_of_ts must be timezone-aware (UTC)")

    result = await session.execute(
        select(UniverseMembership.symbol)
        .where(
            UniverseMembership.universe_id == universe_id,
            UniverseMembership.effective_from <= as_of_ts,
            or_(
                UniverseMembership.effective_to.is_(None),
                UniverseMembership.effective_to > as_of_ts,
            ),
            UniverseMembership.knowledge_ts <= as_of_ts,
        )
        .order_by(UniverseMembership.symbol)
    )
    return [row[0] for row in result.all()]


async def members_over_window(
    session: AsyncSession,
    universe_id: str,
    start: datetime,
    end: datetime,
) -> list[str]:
    """Get all symbols that were members at any point during [start, end].

    Useful for backfills: ensures we compute features for symbols that
    were members at any point in the window, including those later delisted.

    Returns:
        Sorted deduplicated list of canonical symbols.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware (UTC)")

    result = await session.execute(
        select(UniverseMembership.symbol)
        .where(
            UniverseMembership.universe_id == universe_id,
            UniverseMembership.effective_from <= end,
            or_(
                UniverseMembership.effective_to.is_(None),
                UniverseMembership.effective_to > start,
            ),
            UniverseMembership.knowledge_ts <= end,
        )
        .distinct()
        .order_by(UniverseMembership.symbol)
    )
    return [row[0] for row in result.all()]


async def resolve(
    session: AsyncSession,
    identifier: str,
    alias_type: str = "ticker",
    as_of_ts: datetime | None = None,
) -> str | None:
    """Resolve an external identifier to the canonical symbol.

    Handles ticker changes (FB → META), CUSIP changes, etc.

    Args:
        session: Database session.
        identifier: The external identifier value (e.g., "FB", "META").
        alias_type: Type of identifier ("ticker", "cusip", "isin", "figi").
        as_of_ts: Point in time for resolution. If None, returns current.

    Returns:
        Canonical symbol string, or None if not found.
    """
    query = select(SecurityAlias.canonical_symbol).where(
        SecurityAlias.alias_type == alias_type,
        SecurityAlias.alias_value == identifier,
    )

    if as_of_ts is not None:
        query = query.where(
            SecurityAlias.effective_from <= as_of_ts,
            or_(
                SecurityAlias.effective_to.is_(None),
                SecurityAlias.effective_to > as_of_ts,
            ),
        )
    else:
        query = query.where(SecurityAlias.effective_to.is_(None))

    query = query.order_by(SecurityAlias.effective_from.desc()).limit(1)
    result = await session.execute(query)
    row = result.scalar_one_or_none()
    return row


async def get_security(
    session: AsyncSession,
    symbol: str,
) -> SecurityMaster | None:
    """Look up a security by canonical symbol."""
    result = await session.execute(select(SecurityMaster).where(SecurityMaster.symbol == symbol))
    return result.scalar_one_or_none()


async def is_active(
    session: AsyncSession,
    symbol: str,
    as_of_ts: datetime | None = None,
) -> bool:
    """Check if a security is active (not delisted) as of a given time."""
    sec = await get_security(session, symbol)
    if sec is None:
        return False
    if sec.delisted_at is None:
        return True
    if as_of_ts is not None:
        return sec.delisted_at > as_of_ts
    return False
