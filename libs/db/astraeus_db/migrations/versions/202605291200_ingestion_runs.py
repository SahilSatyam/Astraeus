"""add ingestion_runs table

Revision ID: 202605291200
Revises: 202605281200
Create Date: 2026-05-29 12:00:00+00:00

Adds persistent tracking for ingestion runs so run status survives
process restarts and is queryable via the API.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "202605291200"
down_revision: str = "202605281200"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("run_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False, index=True),
        sa.Column("symbols", JSONB, nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("resolution", sa.String(8), nullable=False, server_default="1d"),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("rows_fetched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rows_written", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rows_skipped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("errors", JSONB, nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ingestion_runs_status", "ingestion_runs", ["status"])
    op.create_index("ix_ingestion_runs_started_at", "ingestion_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_runs_started_at")
    op.drop_index("ix_ingestion_runs_status")
    op.drop_table("ingestion_runs")
