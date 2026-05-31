"""SQLAlchemy ORM models for the trading domain.

Tables: order_t, order_event, fill, position, reconciliation_diff,
kill_switch_state, trade_journal.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from astraeus_db import Base


class OrderModel(Base):
    """Persistent order record. State is mirrored from the latest event."""

    __tablename__ = "order_t"

    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True
    )
    client_order_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    account_id: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_id: Mapped[str] = mapped_column(Text, nullable=False)
    rec_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    decision_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    qty: Mapped[str] = mapped_column(Numeric(20, 8), nullable=False)
    order_type: Mapped[str] = mapped_column(Text, nullable=False)
    limit_price: Mapped[str | None] = mapped_column(Numeric(20, 8), nullable=True)
    tif: Mapped[str] = mapped_column(Text, nullable=False, default="DAY")
    state: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_to: Mapped[str] = mapped_column(Text, nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("side IN ('buy', 'sell')", name="ck_order_side"),
        Index("ix_order_account_strategy", "account_id", "strategy_id"),
    )


class OrderEventModel(Base):
    """Append-only order event log for event sourcing."""

    __tablename__ = "order_event"

    event_seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("ix_order_event_order_seq", "order_id", "event_seq"),
    )


class FillModel(Base):
    """Individual fill record."""

    __tablename__ = "fill"

    fill_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    order_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    qty: Mapped[str] = mapped_column(Numeric(20, 8), nullable=False)
    price: Mapped[str] = mapped_column(Numeric(20, 8), nullable=False)
    fees: Mapped[str] = mapped_column(Numeric(20, 8), nullable=False, default="0")
    venue: Mapped[str | None] = mapped_column(Text, nullable=True)
    broker_fill_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("order_id", "broker_fill_id", name="uq_fill_order_broker"),
    )


class PositionModel(Base):
    """Current position snapshot per account/symbol."""

    __tablename__ = "position"

    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    qty: Mapped[str] = mapped_column(Numeric(20, 8), nullable=False)
    avg_cost: Mapped[str] = mapped_column(Numeric(20, 8), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )


class ReconciliationDiffModel(Base):
    """Detected drift between local state and broker state."""

    __tablename__ = "reconciliation_diff"

    diff_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    account_id: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    local_repr: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    broker_repr: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)


class KillSwitchStateModel(Base):
    """Kill switch state per scope (global, account, strategy)."""

    __tablename__ = "kill_switch_state"

    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    armed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    armed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    armed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class TradeJournalModel(Base):
    """Append-only audit log. UPDATE/DELETE revoked at DB level."""

    __tablename__ = "trade_journal"

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    written_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_trade_journal_account", "account_id"),
    )
