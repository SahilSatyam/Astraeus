"""phase3: strategy registry and backtest run tables

Revision ID: 202605291400
Revises: 202605291300
Create Date: 2026-05-29 14:00:00+00:00

Creates:
- strategy: registered strategy definitions catalog
- backtest_run: individual run results with full lineage
- Indexes on strategy_hash, run_hash, strategy_id
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
    op.create_index("ix_strategy_hash", "strategy", ["strategy_hash"], unique=True)
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
    op.create_index("ix_backtest_run_hash", "backtest_run", ["run_hash"], unique=True)
    op.create_index("ix_backtest_run_strategy_id", "backtest_run", ["strategy_id"])
    op.create_index("ix_backtest_run_created", "backtest_run", ["created_at"])
    op.create_index("ix_backtest_run_status", "backtest_run", ["status"])

    # Foreign key: backtest_run.strategy_id → strategy.id
    op.create_foreign_key(
        "fk_backtest_run_strategy",
        "backtest_run",
        "strategy",
        ["strategy_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_backtest_run_strategy", "backtest_run", type_="foreignkey")
    op.drop_table("backtest_run")
    op.drop_table("strategy")
