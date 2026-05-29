"""Strategy registry — content-addressable run tracking.

Every backtest run is identified by a deterministic run_hash. Two runs
with the same hash MUST produce byte-identical artifacts.

Tables:
- strategy: registered strategy definitions
- backtest_run: individual run results with full lineage
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from astraeus_db.base import Base
from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column


class StrategyEntry(Base):
    """Registered strategy in the catalog."""

    __tablename__ = "strategy"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    code_commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    code_path: Mapped[str] = mapped_column(Text, nullable=False)
    params_default: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    dependency_spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    strategy_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class BacktestRun(Base):
    """A single backtest run with full lineage for reproducibility."""

    __tablename__ = "backtest_run"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    engine: Mapped[str] = mapped_column(String(16), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False)
    cost_model_version: Mapped[str] = mapped_column(String(16), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    date_range_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    date_range_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    universe_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    data_lineage_hashes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    artifacts_uri: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    machine_fingerprint: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def compute_run_hash(
    code_commit_sha: str,
    params: dict[str, Any],
    data_lineage_hashes: dict[str, str],
    feature_versions: dict[str, str],
    engine_version: str,
    cost_model_version: str,
    seed: int,
) -> str:
    """Compute deterministic run hash for content-addressable identification.

    Same code + same params + same data + same seed = same hash.
    """
    canonical = json.dumps(
        {
            "code_commit_sha": code_commit_sha,
            "params": params,
            "data_lineage_hashes": data_lineage_hashes,
            "feature_versions": feature_versions,
            "engine_version": engine_version,
            "cost_model_version": cost_model_version,
            "seed": seed,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
