"""SQLAlchemy ORM models for the recommendation engine.

Maps to the Phase 7 schema: recommender_run, regime_state, signal_value,
ensemble_weight, recommendation, recommendation_decision, risk_rejection.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from astraeus_db.base import Base
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column


class RecommenderRun(Base):
    """Pipeline run tracking table."""

    __tablename__ = "recommender_run"

    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued"
    )
    input_snapshot_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    code_commit: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class RegimeState(Base):
    """Regime detection results per run."""

    __tablename__ = "regime_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("recommender_run.run_id"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    model: Mapped[str] = mapped_column(String(32), nullable=False, default="hmm_v1")


class SignalValueRow(Base):
    """Signal values per (run, signal, ticker)."""

    __tablename__ = "signal_value"

    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("recommender_run.run_id"), primary_key=True
    )
    signal: Mapped[str] = mapped_column(String(32), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    score_z: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class EnsembleWeightRow(Base):
    """Ensemble weights per (run, signal, regime)."""

    __tablename__ = "ensemble_weight"

    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("recommender_run.run_id"), primary_key=True
    )
    signal: Mapped[str] = mapped_column(String(32), primary_key=True)
    regime: Mapped[str] = mapped_column(String(32), primary_key=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False)


class RecommendationRow(Base):
    """Final recommendations per run."""

    __tablename__ = "recommendation"

    rec_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("recommender_run.run_id"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(
        String(8), CheckConstraint("side IN ('long', 'short', 'flat')"), nullable=False
    )
    target_weight: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    composite_score: Mapped[float] = mapped_column(Float, nullable=False)
    component_attribution: Mapped[dict] = mapped_column(JSONB, nullable=False)
    risk_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    risk_notes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    thesis_run_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="proposed")
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RecommendationDecisionRow(Base):
    """HITL decisions on recommendations."""

    __tablename__ = "recommendation_decision"

    rec_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("recommendation.rec_id"), primary_key=True
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )
    decided_by: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    override_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)


class RiskRejectionRow(Base):
    """Risk gate rejections."""

    __tablename__ = "risk_rejection"

    rec_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    rule: Mapped[str] = mapped_column(String(64), primary_key=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rejected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
