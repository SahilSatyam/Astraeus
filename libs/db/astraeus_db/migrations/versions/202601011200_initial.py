"""initial: create system_health table

Revision ID: 202601011200
Revises:
Create Date: 2026-01-01 12:00:00+00:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "202601011200"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "system_health",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("component", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.execute(
        sa.text(
            "INSERT INTO system_health (component) VALUES ('api') "
            "ON CONFLICT (component) DO NOTHING"
        )
    )


def downgrade() -> None:
    op.drop_table("system_health")
