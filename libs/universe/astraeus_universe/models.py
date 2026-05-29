"""Universe and security master SQLAlchemy models.

Tables:
- universe: Bitemporal membership tracking (which symbols were in which index, when)
- security_master: Canonical symbol registry with FIGI as immutable ID
- security_alias: Ticker/CUSIP/ISIN resolution with effective date ranges

All timestamps are UTC. Universe queries are bitemporal (effective_from/to + knowledge_ts)
to prevent survivorship bias.
"""

from __future__ import annotations

from datetime import datetime

from astraeus_db.base import Base
from sqlalchemy import DateTime, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column


class UniverseMembership(Base):
    """Bitemporal universe membership.

    Tracks which symbols belong to which universe (e.g., S&P 500) over time.
    Both the effective period and the knowledge timestamp are tracked to support
    PIT-correct queries.
    """

    __tablename__ = "universe"
    __table_args__ = (
        Index("ix_universe_lookup", "universe_id", "effective_from", "effective_to"),
        Index("ix_universe_symbol", "symbol", "effective_from"),
    )

    universe_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    knowledge_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    announcement_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason_added: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_removed: Mapped[str | None] = mapped_column(Text, nullable=True)
    successor_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)


class SecurityMaster(Base):
    """Canonical security registry.

    Each symbol is a stable internal identifier. External identifiers
    (tickers, CUSIPs, ISINs) are resolved via security_alias.
    FIGI is the preferred immutable external identifier.
    """

    __tablename__ = "security_master"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    cusip: Mapped[str | None] = mapped_column(String(9), nullable=True)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    figi: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    listed_ticker: Mapped[str | None] = mapped_column(String(16), nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    asset_class: Mapped[str | None] = mapped_column(String(16), nullable=True)
    listing_exchange: Mapped[str | None] = mapped_column(String(16), nullable=True)
    listed_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delisting_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class SecurityAlias(Base):
    """External identifier resolution with effective date ranges.

    Handles ticker changes (FB → META), CUSIP changes, etc.
    """

    __tablename__ = "security_alias"
    __table_args__ = (
        Index("ix_alias_canonical", "canonical_symbol", "alias_type"),
    )

    alias_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    alias_value: Mapped[str] = mapped_column(String(32), primary_key=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    canonical_symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    knowledge_ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
