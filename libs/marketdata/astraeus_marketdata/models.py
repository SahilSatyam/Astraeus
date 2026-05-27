"""Phase 1 SQLAlchemy models for market data.

Tables:
- market_bars_raw: Immutable, unadjusted OHLCV bars (TimescaleDB hypertable)
- market_bars_adjusted: Split/dividend-adjusted bars (rebuilt by adjustment worker)
- corporate_actions: Splits, dividends, etc.
- data_lineage: Per-row provenance chain
- outbox: Transactional outbox for Redpanda relay
- instruments: Symbol master with survivorship tracking
- data_gaps: Detected missing data points
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from astraeus_db.base import Base


class MarketBarRaw(Base):
    """Immutable, unadjusted OHLCV bars. TimescaleDB hypertable on `ts`."""

    __tablename__ = "market_bars_raw"
    __table_args__ = (
        {"comment": "Raw unadjusted market bars — immutable after initial write."},
    )

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    resolution: Mapped[str] = mapped_column(String(8), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    vwap: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    trades: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    ingest_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)


class MarketBarAdjusted(Base):
    """Split/dividend-adjusted bars. Rebuilt by the adjustment worker."""

    __tablename__ = "market_bars_adjusted"
    __table_args__ = (
        {"comment": "Adjusted market bars — rebuilt from raw + corporate actions."},
    )

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    resolution: Mapped[str] = mapped_column(String(8), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    vwap: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    trades: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    ingest_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    adjusted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    adjustment_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)


class CorporateAction(Base):
    """Corporate actions: splits, dividends, spinoffs."""

    __tablename__ = "corporate_actions"
    __table_args__ = (
        UniqueConstraint("symbol", "action_type", "ex_date", "source", name="uq_corp_action"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(16), nullable=False)
    ex_date: Mapped[date] = mapped_column(Date, nullable=False)
    ratio: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    cash_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class DataLineage(Base):
    """Per-row provenance: traces any row back to its source response."""

    __tablename__ = "data_lineage"
    __table_args__ = (
        Index("ix_lineage_lookup", "target_table", "target_pk", "written_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    target_table: Mapped[str] = mapped_column(String(64), nullable=False)
    target_pk: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_endpoint: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_response_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    source_response_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    ingest_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    written_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Outbox(Base):
    """Transactional outbox — drained by relay into Redpanda."""

    __tablename__ = "outbox"
    __table_args__ = (
        Index("ix_outbox_unpublished", "published_at", postgresql_where=text("published_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Instrument(Base):
    """Symbol master with survivorship-bias tracking."""

    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(16), nullable=False)
    primary_exchange: Mapped[str | None] = mapped_column(String(16), nullable=True)
    listed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    delisted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        comment="Derived: true when delisted_at IS NULL",
    )


class DataGap(Base):
    """Detected missing data points vs market calendar expectations."""

    __tablename__ = "data_gaps"
    __table_args__ = (
        UniqueConstraint("symbol", "resolution", "expected_ts", name="uq_data_gap"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    resolution: Mapped[str] = mapped_column(String(8), nullable=False)
    expected_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
