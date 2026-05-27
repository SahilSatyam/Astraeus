"""phase1: market data tables

Revision ID: 202605271200
Revises: 202601011200
Create Date: 2026-05-27 12:00:00+00:00

Creates:
- market_bars_raw (TimescaleDB hypertable)
- market_bars_adjusted (TimescaleDB hypertable)
- corporate_actions
- data_lineage
- outbox
- instruments
- data_gaps
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "202605271200"
down_revision: str = "202601011200"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Ensure TimescaleDB extension is available
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))

    # --- market_bars_raw ---
    # Note: TimescaleDB hypertables require the time column in all unique indexes.
    # We use (symbol, ts, resolution, source) as the composite primary key
    # instead of a surrogate id to satisfy this constraint.
    op.execute(
        sa.text("""
            CREATE TABLE market_bars_raw (
                symbol         VARCHAR(32)    NOT NULL,
                ts             TIMESTAMPTZ    NOT NULL,
                resolution     VARCHAR(8)     NOT NULL,
                open           NUMERIC(20,8)  NOT NULL,
                high           NUMERIC(20,8)  NOT NULL,
                low            NUMERIC(20,8)  NOT NULL,
                close          NUMERIC(20,8)  NOT NULL,
                volume         BIGINT,
                vwap           NUMERIC(20,8),
                trades         INTEGER,
                source         VARCHAR(32)    NOT NULL,
                schema_version SMALLINT       NOT NULL,
                ingest_run_id  UUID           NOT NULL,
                payload_hash   BYTEA          NOT NULL,
                PRIMARY KEY (symbol, ts, resolution, source)
            )
        """)
    )

    op.execute(
        sa.text(
            "SELECT create_hypertable('market_bars_raw', 'ts', "
            "chunk_time_interval => INTERVAL '7 days')"
        )
    )
    op.create_index("ix_bars_raw_run", "market_bars_raw", ["ingest_run_id"])
    op.create_index("ix_bars_raw_symbol", "market_bars_raw", ["symbol", "ts"])

    # --- market_bars_adjusted ---
    op.execute(
        sa.text("""
            CREATE TABLE market_bars_adjusted (
                symbol          VARCHAR(32)    NOT NULL,
                ts              TIMESTAMPTZ    NOT NULL,
                resolution      VARCHAR(8)     NOT NULL,
                open            NUMERIC(20,8)  NOT NULL,
                high            NUMERIC(20,8)  NOT NULL,
                low             NUMERIC(20,8)  NOT NULL,
                close           NUMERIC(20,8)  NOT NULL,
                volume          BIGINT,
                vwap            NUMERIC(20,8),
                trades          INTEGER,
                source          VARCHAR(32)    NOT NULL,
                schema_version  SMALLINT       NOT NULL,
                ingest_run_id   UUID           NOT NULL,
                payload_hash    BYTEA          NOT NULL,
                adjusted_at     TIMESTAMPTZ    NOT NULL,
                adjustment_hash BYTEA          NOT NULL,
                PRIMARY KEY (symbol, ts, resolution, source)
            )
        """)
    )

    op.execute(
        sa.text(
            "SELECT create_hypertable('market_bars_adjusted', 'ts', "
            "chunk_time_interval => INTERVAL '7 days')"
        )
    )
    op.create_index("ix_bars_adj_run", "market_bars_adjusted", ["ingest_run_id"])
    op.create_index("ix_bars_adj_symbol", "market_bars_adjusted", ["symbol", "ts"])

    # --- corporate_actions ---
    op.create_table(
        "corporate_actions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("action_type", sa.String(16), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("ratio", sa.Numeric(20, 10), nullable=True),
        sa.Column("cash_amount", sa.Numeric(20, 8), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("raw_payload", JSONB(), nullable=True),
        sa.UniqueConstraint(
            "symbol", "action_type", "ex_date", "source", name="uq_corp_action"
        ),
    )

    # --- data_lineage ---
    op.create_table(
        "data_lineage",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("target_table", sa.String(64), nullable=False),
        sa.Column("target_pk", JSONB(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_endpoint", sa.Text(), nullable=True),
        sa.Column("source_response_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("source_response_uri", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.SmallInteger(), nullable=False),
        sa.Column("ingest_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "written_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_lineage_lookup",
        "data_lineage",
        ["target_table", "target_pk", "written_at"],
    )

    # --- outbox ---
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("topic", sa.String(128), nullable=False),
        sa.Column("key", sa.LargeBinary(), nullable=True),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("headers", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_outbox_unpublished ON outbox (published_at) "
            "WHERE published_at IS NULL"
        )
    )

    # --- instruments ---
    op.create_table(
        "instruments",
        sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("asset_class", sa.String(16), nullable=False),
        sa.Column("primary_exchange", sa.String(16), nullable=True),
        sa.Column("listed_at", sa.Date(), nullable=True),
        sa.Column("delisted_at", sa.Date(), nullable=True),
        sa.Column("sector", sa.String(64), nullable=True),
        sa.Column("industry", sa.String(64), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="Derived: true when delisted_at IS NULL",
        ),
    )

    # --- data_gaps ---
    op.create_table(
        "data_gaps",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("resolution", sa.String(8), nullable=False),
        sa.Column("expected_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("symbol", "resolution", "expected_ts", name="uq_data_gap"),
    )

    # Compression policy for older chunks (>30 days)
    op.execute(
        sa.text(
            "ALTER TABLE market_bars_raw SET ("
            "timescaledb.compress, "
            "timescaledb.compress_segmentby = 'symbol,source'"
            ")"
        )
    )
    op.execute(
        sa.text(
            "SELECT add_compression_policy('market_bars_raw', INTERVAL '30 days')"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE market_bars_adjusted SET ("
            "timescaledb.compress, "
            "timescaledb.compress_segmentby = 'symbol,source'"
            ")"
        )
    )
    op.execute(
        sa.text(
            "SELECT add_compression_policy('market_bars_adjusted', INTERVAL '30 days')"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("SELECT remove_compression_policy('market_bars_adjusted', if_exists => true)"))
    op.execute(sa.text("SELECT remove_compression_policy('market_bars_raw', if_exists => true)"))
    op.drop_table("data_gaps")
    op.drop_table("instruments")
    op.drop_table("outbox")
    op.drop_table("data_lineage")
    op.drop_table("corporate_actions")
    op.drop_table("market_bars_adjusted")
    op.drop_table("market_bars_raw")
