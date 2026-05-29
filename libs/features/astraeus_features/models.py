"""Feature store SQLAlchemy models.

Tables:
- feature_registry: Catalog of all registered feature definitions
- feature tables follow the canonical bitemporal shape:
  (symbol, event_ts, knowledge_ts, value, value_version, source_hash)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from astraeus_db.base import Base
from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column


class FeatureRegistry(Base):
    """Catalog of all registered feature definitions.

    Every feature defined via the DSL gets an entry here. The definition_hash
    is the version — same hash means same transform logic.
    """

    __tablename__ = "feature_registry"
    __table_args__ = (
        Index("ix_feature_registry_group", "group"),
        Index("ix_feature_registry_hash", "definition_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    group: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str] = mapped_column(String(16), nullable=False, default="symbol")
    dtype: Mapped[str] = mapped_column(String(32), nullable=False, default="numeric")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    dependencies: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    transform_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    materialization: Mapped[str] = mapped_column(String(16), nullable=False, default="incremental")
    freshness_sla_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    knowledge_lag_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tags: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    code_commit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MaterializationRun(Base):
    """Tracks feature materialization runs for lineage and resumability."""

    __tablename__ = "feature_materialization_runs"
    __table_args__ = (
        Index("ix_mat_run_feature", "feature_name", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    feature_name: Mapped[str] = mapped_column(String(128), nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
