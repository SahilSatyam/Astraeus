"""phase8: Live trading infrastructure — OMS, EMS, risk, reconciliation, kill switches

Revision ID: 202605311400
Revises: 202605311300
Create Date: 2026-05-31 14:00:00+00:00

Creates:
- order_t: order records with state machine
- order_event: append-only event log for event sourcing
- fill: individual fill records
- position: current position snapshot per account/symbol
- reconciliation_diff: detected drift between local and broker state
- kill_switch_state: kill switch state per scope
- trade_journal: append-only audit log (UPDATE/DELETE revoked)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "202605311400"
down_revision: str = "202605311300"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- order_t ---
    op.create_table(
        "order_t",
        sa.Column("order_id", UUID(as_uuid=False), primary_key=True),
        sa.Column("client_order_id", sa.Text(), nullable=False, unique=True),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("strategy_id", sa.Text(), nullable=False),
        sa.Column("rec_id", UUID(as_uuid=False), nullable=True),
        sa.Column("decision_id", UUID(as_uuid=False), nullable=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("qty", sa.Numeric(20, 8), nullable=False),
        sa.Column("order_type", sa.Text(), nullable=False),
        sa.Column("limit_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("tif", sa.Text(), nullable=False, server_default="DAY"),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("submitted_to", sa.Text(), nullable=False),
        sa.Column("broker_order_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="ck_order_side"),
    )
    op.create_index("ix_order_account_strategy", "order_t", ["account_id", "strategy_id"])

    # --- order_event ---
    op.create_table(
        "order_event",
        sa.Column("event_seq", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("order_id", UUID(as_uuid=False), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["order_t.order_id"], name="fk_order_event_order"),
    )
    op.create_index("ix_order_event_order_seq", "order_event", ["order_id", "event_seq"])

    # --- fill ---
    op.create_table(
        "fill",
        sa.Column("fill_id", UUID(as_uuid=False), primary_key=True),
        sa.Column("order_id", UUID(as_uuid=False), nullable=False),
        sa.Column("qty", sa.Numeric(20, 8), nullable=False),
        sa.Column("price", sa.Numeric(20, 8), nullable=False),
        sa.Column("fees", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("venue", sa.Text(), nullable=True),
        sa.Column("broker_fill_id", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["order_id"], ["order_t.order_id"], name="fk_fill_order"),
        sa.UniqueConstraint("order_id", "broker_fill_id", name="uq_fill_order_broker"),
    )

    # --- position ---
    op.create_table(
        "position",
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("qty", sa.Numeric(20, 8), nullable=False),
        sa.Column("avg_cost", sa.Numeric(20, 8), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("account_id", "symbol"),
    )

    # --- reconciliation_diff ---
    op.create_table(
        "reconciliation_diff",
        sa.Column("diff_id", UUID(as_uuid=False), primary_key=True),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("local_repr", JSONB, nullable=True),
        sa.Column("broker_repr", JSONB, nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
    )

    # --- kill_switch_state ---
    op.create_table(
        "kill_switch_state",
        sa.Column("scope", sa.Text(), primary_key=True),
        sa.Column("armed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("armed_by", sa.Text(), nullable=True),
        sa.Column("armed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
    )

    # --- trade_journal ---
    op.create_table(
        "trade_journal",
        sa.Column("seq", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("written_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_trade_journal_account", "trade_journal", ["account_id"])

    # Enforce append-only on trade_journal
    op.execute("REVOKE UPDATE, DELETE ON trade_journal FROM PUBLIC;")


def downgrade() -> None:
    op.execute("GRANT UPDATE, DELETE ON trade_journal TO PUBLIC;")
    op.drop_table("trade_journal")
    op.drop_table("kill_switch_state")
    op.drop_table("reconciliation_diff")
    op.drop_table("position")
    op.drop_table("fill")
    op.drop_table("order_event")
    op.drop_table("order_t")
