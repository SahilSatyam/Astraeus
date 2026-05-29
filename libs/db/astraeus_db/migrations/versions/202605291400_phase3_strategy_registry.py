"""phase3: strategy registry and backtest run tables

Revision ID: 202605291400
Revises: 202605291300
Create Date: 2026-05-29 14:00:00+00:00

Creates:
- strategy: registered strategy definitions
- backtest_run: content-addressable backtest results
- signal_panel: daily signal output for downstream consumers
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "202605291400"
down_revision: str = "202605291300"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- strategy ---
    op.create_table(
        "strategy",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("code_commit_sha", sa.String(40), nullable=False),
        sa.Column("code_path", sa.Text, nullable=False),
        sa.Column("params_default", JSONB, nullable=True),
        sa.Column("dependency_spec", JSONB, nullable=True),
        sa.Column("strategy_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(64), nullable=True),
    )
    op.create_index("ix_strategy_name_version", "strategy", ["name", "version"])
    op.create_index("ix_strategy_status", "strategy", ["status"])

    # --- backtest_run ---
    op.create_table(
        "backtest_run",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("strategy_id", UUID(as_uuid=True), nullable=False),
        sa.Column("run_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("engine", sa.String(16), nullable=False),
        sa.Column("engine_version", sa.String(16), nullable=False),
        sa.Column("cost_model_version", sa.String(16), nullable=False),
        sa.Column("params", JSONB, nullable=False),
        sa.Column("seed", sa.BigInteger, nullable=False),
        sa.Column("date_range_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("date_range_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("universe_snapshot_id", sa.String(64), nullable=False),
        sa.Column("feature_versions", JSONB, nullable=False),
        sa.Column("data_lineage_hashes", JSONB, nullable=False),
        sa.Column("metrics", JSONB, nullable=False),
        sa.Column("artifacts_uri", sa.Text, nullable=False),
        sa.Column("duration_seconds", sa.Integer, nullable=True),
        sa.Column("machine_fingerprint", JSONB, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="completed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_backtest_run_strategy", "backtest_run", ["strategy_id", "created_at"])
    op.create_index("ix_backtest_run_status", "backtest_run", ["status"])

    # --- signal_panel ---
    op.execute(sa.text("""
        CREATE TABLE signal_panel (
            ts             DATE         NOT NULL,
            symbol         TEXT         NOT NULL,
            strategy_id    UUID         NOT NULL,
            run_hash       TEXT         NOT NULL,
            raw_score      DOUBLE PRECISION,
            ranked_score   DOUBLE PRECISION,
            target_weight  DOUBLE PRECISION,
            confidence     DOUBLE PRECISION,
            PRIMARY KEY (ts, symbol, strategy_id)
        )
    """))
    op.execute(sa.text(
        "SELECT create_hypertable('signal_panel', 'ts', "
        "chunk_time_interval => INTERVAL '90 days', if_not_exists => TRUE)"
    ))
    op.create_index("ix_signal_panel_strategy", "signal_panel", ["strategy_id", "ts"])


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS signal_panel"))
    op.drop_table("backtest_run")
    op.drop_table("strategy")
