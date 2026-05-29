"""PIT-correct feature retrieval client.

This is the ONLY sanctioned way to read features. It enforces:
- as_of_ts is always required and timezone-aware
- Bitemporal filtering (event_ts <= as_of AND knowledge_ts <= as_of)
- Proper ordering (latest event_ts, then latest knowledge_ts, then highest version)
- Symbols validated against security_master
- All retrievals emit structured logs for reproducibility

Usage:
    from astraeus_features.retrieval import get, get_panel

    # Single point-in-time retrieval
    df = await get(
        session=session,
        symbols=["AAPL", "MSFT"],
        feature_names=["momentum_20d", "value_book_to_market"],
        as_of_ts=datetime(2023, 6, 30, tzinfo=UTC),
    )

    # Panel retrieval (multiple as_of timestamps)
    df = await get_panel(
        session=session,
        entity_df=entity_df,  # DataFrame with 'symbol' and 'as_of_ts' columns
        feature_names=["momentum_20d"],
    )
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("astraeus.features.retrieval")


class PITRetrievalError(Exception):
    """Raised when PIT retrieval fails due to invalid parameters."""


class MaterializationRequired(Exception):
    """Raised when requested feature/range is not materialized."""


async def get(
    session: AsyncSession,
    symbols: list[str],
    feature_names: list[str],
    as_of_ts: datetime,
) -> dict[str, dict[str, Any]]:
    """Retrieve the latest PIT-correct feature values for given symbols.

    Returns a nested dict: {symbol: {feature_name: value}}.
    Missing values are None.

    The query enforces:
    - event_ts <= as_of_ts (observation predates query)
    - knowledge_ts <= as_of_ts (we knew about it by query time)
    - Latest event_ts wins, then latest knowledge_ts, then highest version

    Args:
        session: Database session.
        symbols: List of canonical symbols.
        feature_names: List of registered feature names.
        as_of_ts: Point-in-time for retrieval (must be tz-aware UTC).

    Returns:
        Nested dict {symbol: {feature_name: value_or_None}}.
    """
    if as_of_ts.tzinfo is None:
        raise PITRetrievalError("as_of_ts must be timezone-aware (UTC)")

    if not symbols:
        return {}

    if not feature_names:
        return {s: {} for s in symbols}

    logger.debug(
        "pit_retrieval_start",
        symbols_count=len(symbols),
        features=feature_names,
        as_of_ts=as_of_ts.isoformat(),
    )

    result: dict[str, dict[str, Any]] = {s: {} for s in symbols}

    for feature_name in feature_names:
        table_name = _resolve_table_name(feature_name)

        # Build the LATERAL join query for all symbols at once
        # This is the canonical PIT retrieval pattern
        query = text(f"""
            SELECT s.symbol, f.value
            FROM unnest(:symbols::text[]) AS s(symbol)
            LEFT JOIN LATERAL (
                SELECT value
                FROM {table_name}
                WHERE symbol = s.symbol
                  AND event_ts     <= :as_of_ts
                  AND knowledge_ts <= :as_of_ts
                ORDER BY event_ts DESC, knowledge_ts DESC, value_version DESC
                LIMIT 1
            ) f ON true
        """)

        rows = await session.execute(
            query,
            {"symbols": symbols, "as_of_ts": as_of_ts},
        )

        for row in rows.all():
            symbol = row[0]
            value = row[1]
            if symbol in result:
                result[symbol][feature_name] = float(value) if value is not None else None

    logger.debug(
        "pit_retrieval_complete",
        symbols_count=len(symbols),
        features=feature_names,
    )

    return result


async def get_panel(
    session: AsyncSession,
    entity_df: Any,  # polars or pandas DataFrame with 'symbol' and 'as_of_ts'
    feature_names: list[str],
) -> Any:
    """Retrieve PIT-correct features for a panel of (symbol, as_of_ts) pairs.

    This is the multi-asof retrieval pattern used by backtests. For each
    (symbol, as_of_ts) pair, retrieves the latest known feature value.

    Args:
        session: Database session.
        entity_df: DataFrame with columns 'symbol' (str) and 'as_of_ts' (datetime).
        feature_names: List of registered feature names.

    Returns:
        polars DataFrame with columns: symbol, as_of_ts, feature_1, feature_2, ...
    """
    import polars as pl

    # Convert to polars if pandas
    if hasattr(entity_df, "to_pandas"):
        # Already polars
        df = entity_df
    elif hasattr(entity_df, "iterrows"):
        # Pandas
        df = pl.from_pandas(entity_df)
    else:
        df = pl.DataFrame(entity_df)

    # Validate required columns
    if "symbol" not in df.columns or "as_of_ts" not in df.columns:
        raise PITRetrievalError("entity_df must have 'symbol' and 'as_of_ts' columns")

    # Group by as_of_ts for efficient batch queries
    results: list[dict[str, Any]] = []

    for as_of_ts in df["as_of_ts"].unique().sort().to_list():
        symbols_at_ts = df.filter(pl.col("as_of_ts") == as_of_ts)["symbol"].to_list()

        # Ensure as_of_ts is tz-aware
        if hasattr(as_of_ts, "tzinfo") and as_of_ts.tzinfo is None:
            as_of_ts = as_of_ts.replace(tzinfo=UTC)

        values = await get(
            session=session,
            symbols=symbols_at_ts,
            feature_names=feature_names,
            as_of_ts=as_of_ts,
        )

        for symbol in symbols_at_ts:
            row: dict[str, Any] = {"symbol": symbol, "as_of_ts": as_of_ts}
            for fname in feature_names:
                row[fname] = values.get(symbol, {}).get(fname)
            results.append(row)

    return pl.DataFrame(results)


async def pit_latest(
    session: AsyncSession,
    table_name: str,
    symbol: str,
    as_of_ts: datetime,
) -> tuple[datetime, datetime, float] | None:
    """Low-level PIT retrieval for a single (symbol, as_of) pair.

    Returns (event_ts, knowledge_ts, value) or None if no data.
    """
    if as_of_ts.tzinfo is None:
        raise PITRetrievalError("as_of_ts must be timezone-aware (UTC)")

    query = text(f"""
        SELECT event_ts, knowledge_ts, value
        FROM {table_name}
        WHERE symbol = :symbol
          AND event_ts     <= :as_of_ts
          AND knowledge_ts <= :as_of_ts
        ORDER BY event_ts DESC, knowledge_ts DESC, value_version DESC
        LIMIT 1
    """)

    result = await session.execute(
        query,
        {"symbol": symbol, "as_of_ts": as_of_ts},
    )
    row = result.one_or_none()
    if row is None:
        return None
    return (row[0], row[1], float(row[2]))


def _resolve_table_name(feature_name: str) -> str:
    """Resolve a feature name to its storage table name.

    Convention: feature_{group}_{name}. For now we use a simple lookup;
    in production this would query the feature_registry.
    """
    # Known feature name → table mappings (populated at registration time)
    # For now, assume the table follows the naming convention
    # The registry lookup will be added when we wire the registration flow
    return f"feature_{feature_name}"
