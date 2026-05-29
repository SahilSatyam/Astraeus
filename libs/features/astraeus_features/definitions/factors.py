"""Core factor definitions for the Phase 2 exit notebook.

These 5 factors are computed monthly across the universe and form the
basis of the long-short decile portfolio analysis.
"""

from __future__ import annotations

from datetime import timedelta

from astraeus_features.dsl import Entity, FeatureDefinition, sql_transform

# --- Momentum: 12-1 month return (skip most recent month) ---

momentum_12_1 = FeatureDefinition(
    name="momentum_12_1",
    group="price_derived",
    entity=Entity.SYMBOL,
    dtype="numeric",
    description="12-1 month price momentum. Log return from t-252 to t-21 trading days.",
    dependencies=["market_bars_raw"],
    freshness_sla=timedelta(hours=4),
    knowledge_lag=timedelta(0),
    materialization="incremental",
    transform=sql_transform("""
        WITH prices AS (
            SELECT
                symbol,
                ts AS event_ts,
                ts AS knowledge_ts,
                close,
                LAG(close, 21) OVER (PARTITION BY symbol ORDER BY ts) AS close_21,
                LAG(close, 252) OVER (PARTITION BY symbol ORDER BY ts) AS close_252
            FROM market_bars_raw
            WHERE resolution = '1d'
              AND event_ts <= :as_of
        )
        SELECT
            symbol,
            event_ts,
            knowledge_ts,
            LN(close_21 / NULLIF(close_252, 0)) AS value,
            1 AS value_version
        FROM prices
        WHERE close_21 IS NOT NULL
          AND close_252 IS NOT NULL
          AND close_252 > 0
    """),
    owner="quant-research",
    tags=["factor", "momentum", "exit-criteria"],
)

# --- Value: Book-to-Market ratio ---

value_book_to_market = FeatureDefinition(
    name="value_book_to_market",
    group="fundamentals",
    entity=Entity.SYMBOL,
    dtype="numeric",
    description="Book-to-market ratio. Book value per share / market price.",
    dependencies=["market_bars_raw"],
    freshness_sla=timedelta(hours=24),
    knowledge_lag=timedelta(days=1),
    materialization="incremental",
    transform=sql_transform("""
        SELECT
            symbol,
            event_ts,
            knowledge_ts,
            value,
            value_version
        FROM feature_fundamentals_book_to_market
        WHERE event_ts <= :as_of
          AND knowledge_ts <= :as_of
    """),
    owner="quant-research",
    tags=["factor", "value", "exit-criteria"],
)

# --- Quality: Return on Equity (TTM) ---

quality_roe = FeatureDefinition(
    name="quality_roe",
    group="fundamentals",
    entity=Entity.SYMBOL,
    dtype="numeric",
    description="Return on equity, trailing twelve months.",
    dependencies=["market_bars_raw"],
    freshness_sla=timedelta(hours=24),
    knowledge_lag=timedelta(days=1),
    materialization="incremental",
    transform=sql_transform("""
        SELECT
            symbol,
            event_ts,
            knowledge_ts,
            value,
            value_version
        FROM feature_fundamentals_roe
        WHERE event_ts <= :as_of
          AND knowledge_ts <= :as_of
    """),
    owner="quant-research",
    tags=["factor", "quality", "exit-criteria"],
)

# --- Low Volatility: 60-day realized vol (sign-flipped) ---

low_vol_60d = FeatureDefinition(
    name="low_vol_60d",
    group="price_derived",
    entity=Entity.SYMBOL,
    dtype="numeric",
    description="60-day realized volatility, sign-flipped (lower vol = higher score).",
    dependencies=["market_bars_raw"],
    freshness_sla=timedelta(hours=4),
    knowledge_lag=timedelta(0),
    materialization="incremental",
    transform=sql_transform("""
        WITH daily_returns AS (
            SELECT
                symbol,
                ts AS event_ts,
                ts AS knowledge_ts,
                LN(close / NULLIF(LAG(close) OVER (PARTITION BY symbol ORDER BY ts), 0)) AS log_ret
            FROM market_bars_raw
            WHERE resolution = '1d'
              AND event_ts <= :as_of
        ),
        vol AS (
            SELECT
                symbol,
                event_ts,
                knowledge_ts,
                STDDEV(log_ret) OVER (
                    PARTITION BY symbol ORDER BY event_ts
                    ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
                ) * SQRT(252) AS annualized_vol
            FROM daily_returns
            WHERE log_ret IS NOT NULL
        )
        SELECT
            symbol,
            event_ts,
            knowledge_ts,
            -1.0 * annualized_vol AS value,
            1 AS value_version
        FROM vol
        WHERE annualized_vol IS NOT NULL
    """),
    owner="quant-research",
    tags=["factor", "low-vol", "exit-criteria"],
)

# --- Size: Log market cap (sign-flipped) ---

size_log_mcap = FeatureDefinition(
    name="size_log_mcap",
    group="fundamentals",
    entity=Entity.SYMBOL,
    dtype="numeric",
    description="Log market cap, sign-flipped (smaller = higher score for SMB factor).",
    dependencies=["market_bars_raw"],
    freshness_sla=timedelta(hours=24),
    knowledge_lag=timedelta(days=1),
    materialization="incremental",
    transform=sql_transform("""
        SELECT
            symbol,
            event_ts,
            knowledge_ts,
            -1.0 * value AS value,
            value_version
        FROM feature_fundamentals_log_mcap
        WHERE event_ts <= :as_of
          AND knowledge_ts <= :as_of
    """),
    owner="quant-research",
    tags=["factor", "size", "exit-criteria"],
)
