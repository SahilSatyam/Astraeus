"""continuous aggregates for OHLCV rollups

Revision ID: 202605281200
Revises: 202605271200
Create Date: 2026-05-28 12:00:00+00:00

Creates TimescaleDB continuous aggregates for automatic OHLCV rollups:
- market_bars_hourly: 1-hour rollup from raw bars
- market_bars_daily_agg: Daily rollup (useful when ingesting minute/hourly data)
- market_bars_weekly: Weekly rollup from daily data

These are materialized views that TimescaleDB refreshes automatically,
providing fast pre-computed aggregations without manual cron jobs.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "202605281200"
down_revision: str = "202605271200"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- Hourly rollup from raw bars ---
    op.execute(
        sa.text("""
            CREATE MATERIALIZED VIEW market_bars_hourly
            WITH (timescaledb.continuous) AS
            SELECT
                symbol,
                source,
                time_bucket('1 hour', ts) AS bucket,
                FIRST(open, ts) AS open,
                MAX(high) AS high,
                MIN(low) AS low,
                LAST(close, ts) AS close,
                SUM(volume) AS volume,
                SUM(volume * vwap) / NULLIF(SUM(volume), 0) AS vwap,
                SUM(trades) AS trades,
                COUNT(*) AS bar_count
            FROM market_bars_raw
            WHERE resolution = '1m' OR resolution = '5m'
            GROUP BY symbol, source, bucket
            WITH NO DATA
        """)
    )

    # Refresh policy: refresh hourly data that's between 3 hours and 1 hour old
    op.execute(
        sa.text("""
            SELECT add_continuous_aggregate_policy('market_bars_hourly',
                start_offset => INTERVAL '3 hours',
                end_offset => INTERVAL '1 hour',
                schedule_interval => INTERVAL '1 hour'
            )
        """)
    )

    # --- Daily rollup (from minute/hourly bars) ---
    op.execute(
        sa.text("""
            CREATE MATERIALIZED VIEW market_bars_daily_agg
            WITH (timescaledb.continuous) AS
            SELECT
                symbol,
                source,
                time_bucket('1 day', ts) AS bucket,
                FIRST(open, ts) AS open,
                MAX(high) AS high,
                MIN(low) AS low,
                LAST(close, ts) AS close,
                SUM(volume) AS volume,
                SUM(volume * vwap) / NULLIF(SUM(volume), 0) AS vwap,
                SUM(trades) AS trades,
                COUNT(*) AS bar_count
            FROM market_bars_raw
            WHERE resolution IN ('1m', '5m', '15m', '1h')
            GROUP BY symbol, source, bucket
            WITH NO DATA
        """)
    )

    # Refresh policy: refresh daily data that's between 3 days and 1 day old
    op.execute(
        sa.text("""
            SELECT add_continuous_aggregate_policy('market_bars_daily_agg',
                start_offset => INTERVAL '3 days',
                end_offset => INTERVAL '1 day',
                schedule_interval => INTERVAL '1 day'
            )
        """)
    )

    # --- Weekly rollup from daily bars ---
    op.execute(
        sa.text("""
            CREATE MATERIALIZED VIEW market_bars_weekly
            WITH (timescaledb.continuous) AS
            SELECT
                symbol,
                source,
                time_bucket('7 days', ts) AS bucket,
                FIRST(open, ts) AS open,
                MAX(high) AS high,
                MIN(low) AS low,
                LAST(close, ts) AS close,
                SUM(volume) AS volume,
                SUM(volume * vwap) / NULLIF(SUM(volume), 0) AS vwap,
                SUM(trades) AS trades,
                COUNT(*) AS bar_count
            FROM market_bars_raw
            WHERE resolution = '1d'
            GROUP BY symbol, source, bucket
            WITH NO DATA
        """)
    )

    # Refresh policy: refresh weekly data that's between 4 weeks and 1 week old
    # Window must cover at least 2 buckets (2 x 7 days = 14 days minimum)
    op.execute(
        sa.text("""
            SELECT add_continuous_aggregate_policy('market_bars_weekly',
                start_offset => INTERVAL '28 days',
                end_offset => INTERVAL '7 days',
                schedule_interval => INTERVAL '1 day'
            )
        """)
    )


def downgrade() -> None:
    op.execute(sa.text("SELECT remove_continuous_aggregate_policy('market_bars_weekly', if_not_exists => true)"))
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS market_bars_weekly CASCADE"))

    op.execute(sa.text("SELECT remove_continuous_aggregate_policy('market_bars_daily_agg', if_not_exists => true)"))
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS market_bars_daily_agg CASCADE"))

    op.execute(sa.text("SELECT remove_continuous_aggregate_policy('market_bars_hourly', if_not_exists => true)"))
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS market_bars_hourly CASCADE"))
