"""Portfolio construction contracts — shared downstream schemas.

These schemas are consumed by Phase 7 (recommendation engine) and Phase 8
(execution). They are the canonical interop surface for portfolio data.

Published schemas:
- TargetPortfolio: The primary output of Phase 4.
- RiskReport: Full risk metrics for a portfolio.
- RiskRejection: Structured rejection record from the risk gate.
- PortfolioWeight: Single asset weight entry.
- ScenarioResult: Stress scenario outcome.
- ClusterReport: Correlation clustering metrics.
- AttributionResult: PnL attribution (factor or Brinson).

Schema versioning:
- schema_version is monotonically increasing.
- Breaking changes ship as v2 alongside v1.
- Adding optional fields under v1 is allowed.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OptimizerType(StrEnum):
    """Supported optimizer algorithms."""

    MVO = "mvo"
    BLACK_LITTERMAN = "black_litterman"
    RISK_PARITY = "risk_parity"
    CVAR = "cvar"


class CovarianceMethod(StrEnum):
    """Supported covariance estimation methods."""

    SAMPLE = "sample"
    LEDOIT_WOLF = "ledoit_wolf"
    FACTOR_MODEL = "factor_model"


class FallbackAction(StrEnum):
    """Actions taken when a portfolio fails risk validation."""

    CASH = "cash"
    HOLD_PRIOR = "hold_prior"
    RETRY_RELAXED = "retry_relaxed"
    ESCALATE_HITL = "escalate_hitl"


class PortfolioStatus(StrEnum):
    """Status of a published portfolio."""

    PASSED = "passed"
    FALLBACK_APPLIED = "fallback_applied"
    REJECTED = "rejected"


class ScenarioName(StrEnum):
    """Named stress scenarios."""

    GFC_2008 = "gfc_2008"
    COVID_2020 = "covid_2020"
    RATE_SHOCK = "rate_shock"
    FLASH_CRASH = "flash_crash"


# ---------------------------------------------------------------------------
# Component Schemas
# ---------------------------------------------------------------------------


class PortfolioWeight(BaseModel):
    """Single asset weight in a portfolio."""

    symbol: str = Field(max_length=32)
    weight: Decimal = Field(ge=-1.0, le=1.0)
    sector: str | None = None


class ScenarioResult(BaseModel):
    """Result from a single stress scenario."""

    scenario_name: ScenarioName
    scenario_version: str
    total_pnl_pct: Decimal
    factor_contributions: dict[str, Decimal]
    asset_contributions: dict[str, Decimal]
    proxy_estimated_assets: list[str] = Field(default_factory=list)


class ClusterReport(BaseModel):
    """Correlation clustering and concentration metrics."""

    n_clusters: int = 10
    max_cluster_weight: Decimal
    herfindahl_index: Decimal
    effective_n_bets: Decimal
    cluster_assignments: dict[str, int]


class ConstraintDiag(BaseModel):
    """Constraint diagnostic for a solved portfolio."""

    constraint_name: str
    satisfied: bool
    shadow_price: float | None
    slack: float | None
    diagnostic: dict


class FailedCheck(BaseModel):
    """A single failed risk gate check."""

    check_name: str
    threshold: float
    actual_value: float


# ---------------------------------------------------------------------------
# Published Output Schemas
# ---------------------------------------------------------------------------


class TargetPortfolio(BaseModel):
    """Published portfolio schema — consumed by Phase 7 and Phase 8.

    This is the primary output of the Phase 4 portfolio construction pipeline.
    It represents a fully validated (or fallback-applied) target portfolio
    ready for downstream consumption.
    """

    portfolio_id: UUID
    strategy_id: str = Field(max_length=128)
    as_of_ts: datetime
    nav_currency: str = Field(max_length=3, default="USD")
    nav: Decimal
    weights: list[PortfolioWeight] = Field(min_length=1, max_length=500)
    status: PortfolioStatus
    optimizer: OptimizerType
    optimizer_config_hash: str
    constraint_set_hash: str
    covariance_estimator: CovarianceMethod
    expected_return_source: str
    risk_report_id: UUID
    rejection_id: UUID | None = None
    parent_portfolio_id: UUID | None = None
    created_at: datetime
    schema_version: Literal["v1"] = "v1"


class RiskReport(BaseModel):
    """Published risk report schema.

    Contains all risk metrics computed for a portfolio: VaR/CVaR across
    three methods and two confidence levels, stress scenarios, clustering,
    and constraint diagnostics.
    """

    report_id: UUID
    portfolio_id: UUID
    as_of_ts: datetime
    var_95_hist: Decimal
    var_99_hist: Decimal
    cvar_95_hist: Decimal
    cvar_99_hist: Decimal
    var_95_param: Decimal
    cvar_95_param: Decimal
    var_95_mc: Decimal
    cvar_95_mc: Decimal
    stress_scenarios: list[ScenarioResult] = Field(max_length=20)
    cluster_concentration: ClusterReport
    sector_exposure: dict[str, Decimal]
    factor_exposure: dict[str, Decimal]
    beta: Decimal
    effective_n_bets: Decimal
    liquidity_5day_pct: Decimal
    constraint_diagnostics: list[ConstraintDiag] = Field(max_length=50)
    policy_version: str
    schema_version: Literal["v1"] = "v1"


class RiskRejection(BaseModel):
    """Structured rejection record from the risk validation gate.

    Emitted when a portfolio fails the binary risk gate. Contains the
    specific checks that failed and the fallback action taken.
    """

    rejection_id: UUID
    portfolio_id: UUID
    signal_batch_id: UUID
    strategy_id: str
    as_of_ts: datetime
    optimizer: OptimizerType
    policy_version: str
    failed_checks: list[FailedCheck]
    full_report_id: UUID
    fallback_action: FallbackAction
    fallback_outcome: dict | None = None
    created_at: datetime


class AttributionResult(BaseModel):
    """PnL attribution result (factor or Brinson).

    Produced T+1 after portfolio publication, once realized returns
    are available.
    """

    run_id: UUID
    portfolio_id: UUID
    as_of_ts: datetime
    method: Literal["factor_ff5_mom", "brinson"]
    total_pnl_bps: Decimal
    factor_pnl: dict[str, Decimal] | None
    idio_pnl_bps: Decimal | None
    sector_pnl: dict[str, Decimal] | None
    created_at: datetime
