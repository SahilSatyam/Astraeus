"""phase3: strategy indexes and foreign keys (additive)

Revision ID: 202605291401
Revises: 202605291400
Create Date: 2026-05-29 14:01:00+00:00

Adds additional indexes and foreign key constraint to tables
already created in 202605291400.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "202605291401"
down_revision: str = "202605291400"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Add indexes that weren't in the first migration
    op.create_index(
        "ix_backtest_run_hash",
        "backtest_run",
        ["run_hash"],
        unique=True,
        if_not_exists=True,
    )
    op.create_index(
        "ix_backtest_run_created",
        "backtest_run",
        ["created_at"],
        if_not_exists=True,
    )

    # Add FK constraint if not already present
    try:
        op.create_foreign_key(
            "fk_backtest_run_strategy",
            "backtest_run",
            "strategy",
            ["strategy_id"],
            ["id"],
            ondelete="CASCADE",
        )
    except Exception:
        pass  # FK may already exist


def downgrade() -> None:
    try:
        op.drop_constraint("fk_backtest_run_strategy", "backtest_run", type_="foreignkey")
    except Exception:
        pass
    op.drop_index("ix_backtest_run_created", table_name="backtest_run", if_exists=True)
    op.drop_index("ix_backtest_run_hash", table_name="backtest_run", if_exists=True)
