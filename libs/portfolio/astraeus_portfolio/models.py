"""SQLAlchemy 2.0 ORM models for Portfolio Construction & Risk.

Tables:
- target_portfolios: one row per strategy per day (versioned)
- portfolio_weights: one row per asset per portfolio (composite PK)
- risk_reports: JSONB-rich risk metrics per portfolio
- risk_rejections: structured rejection logging with GIN-indexed failed_checks
- attribution_runs: factor-model and Brinson PnL decomposition
- factor_returns: cached Ken French factor data (TimescaleDB hypertable)
- task_runs: idempotency and replay tracking for pipeline tasks
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from astraeus_db.base import Base


class TargetPortfolioModel(Base):
    """Target portfolios — one row per strategy per day, versioned."""

    __tablename__ = "target_portfolios"
    __table_args__ = (
        UniqueConstraint("strategy_id", "as_of_ts", "version", name="uq_target_portfolios_strategy_date_version"),
        Index("idx_target_portfolios_strategy_date", "strategy_id", "as_of_ts"),
        CheckConstraint(
            "status IN ('passed', 'fallback_applied', 'rejected')",
            name="ck_target_portfolios_status",
        ),
    )

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_id: Mapped[str] = mapped_column(Text, nullable=False)
    as_of_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    nav_currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")
    nav: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    optimizer: Mapped[str] = mapped_column(Text, nullable=False)
    optimizer_config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    constraint_set_hash: Mapped[str] = mapped_column(Text, nullable=False)
    covariance_estimator: Mapped[str] = mapped_column(Text, nullable=False)
    expected_return_source: Mapped[str] = mapped_column(Text, nullable=False)
    risk_report_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rejection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    parent_portfolio_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("target_portfolios.portfolio_id"),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    schema_version: Mapped[str] = mapped_column(Text, nullable=False, server_default="v1")

    # Relationships
    weights: Mapped[list["PortfolioWeightModel"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )
    parent_portfolio: Mapped["TargetPortfolioModel | None"] = relationship(
        remote_side="TargetPortfolioModel.portfolio_id",
    )


class PortfolioWeightModel(Base):
    """Portfolio weights — one row per asset per portfolio."""

    __tablename__ = "portfolio_weights"
    __table_args__ = (
        CheckConstraint(
            "weight >= -1.0 AND weight <= 1.0",
            name="ck_portfolio_weights_range",
        ),
    )

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("target_portfolios.portfolio_id"),
        primary_key=True,
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False, primary_key=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    sector: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    portfolio: Mapped["TargetPortfolioModel"] = relationship(back_populates="weights")


class RiskReportModel(Base):
    """Risk reports — JSONB-rich risk metrics per portfolio."""

    __tablename__ = "risk_reports"
    __table_args__ = (
        Index("idx_risk_reports_portfolio", "portfolio_id"),
    )

    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("target_portfolios.portfolio_id"),
        nullable=False,
    )
    as_of_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    var_95_hist: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    var_99_hist: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    cvar_95_hist: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    cvar_99_hist: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    var_95_param: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    cvar_95_param: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    var_95_mc: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    cvar_95_mc: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    stress_scenarios: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    cluster_concentration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    sector_exposure: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    factor_exposure: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    beta: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    effective_n_bets: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    liquidity_5day_pct: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    constraint_diagnostics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    policy_version: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False, server_default="v1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RiskRejectionModel(Base):
    """Risk rejections — structured rejection logging."""

    __tablename__ = "risk_rejections"
    __table_args__ = (
        Index("idx_risk_rejections_strategy_date", "strategy_id", "as_of_ts"),
        Index("idx_risk_rejections_batch", "signal_batch_id"),
        Index("idx_risk_rejections_checks", "failed_checks", postgresql_using="gin"),
    )

    rejection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    signal_batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    strategy_id: Mapped[str] = mapped_column(Text, nullable=False)
    as_of_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    optimizer: Mapped[str] = mapped_column(Text, nullable=False)
    policy_version: Mapped[str] = mapped_column(Text, nullable=False)
    failed_checks: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    full_report_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("risk_reports.report_id"),
        nullable=True,
    )
    fallback_action: Mapped[str] = mapped_column(Text, nullable=False)
    fallback_outcome: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AttributionRunModel(Base):
    """Attribution runs — factor-model and Brinson PnL decomposition."""

    __tablename__ = "attribution_runs"
    __table_args__ = (
        Index("idx_attribution_portfolio_date", "portfolio_id", "as_of_ts"),
        CheckConstraint(
            "method IN ('factor_ff5_mom', 'brinson')",
            name="ck_attribution_runs_method",
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("target_portfolios.portfolio_id"),
        nullable=False,
    )
    as_of_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    total_pnl_bps: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    factor_pnl: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    idio_pnl_bps: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    sector_pnl: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FactorReturnModel(Base):
    """Factor returns — cached Ken French data (TimescaleDB hypertable on factor_date)."""

    __tablename__ = "factor_returns"

    factor_date: Mapped[date] = mapped_column(Date, primary_key=True)
    factor_name: Mapped[str] = mapped_column(Text, primary_key=True)
    daily_return: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="ken_french")
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TaskRunModel(Base):
    """Task runs — idempotency and replay tracking for pipeline tasks."""

    __tablename__ = "task_runs"
    __table_args__ = (
        UniqueConstraint(
            "strategy_id", "as_of_date", "task_name", "version",
            name="uq_task_runs_strategy_date_task_version",
        ),
        Index(
            "idx_task_runs_lookup",
            "strategy_id", "as_of_date", "task_name", "version",
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'timed_out')",
            name="ck_task_runs_status",
        ),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_id: Mapped[str] = mapped_column(Text, nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    task_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    result_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
