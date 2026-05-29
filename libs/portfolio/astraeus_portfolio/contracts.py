"""Core Pydantic data models for portfolio construction and risk."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

import numpy as np
from pydantic import BaseModel, Field, field_validator

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
# Covariance Models
# ---------------------------------------------------------------------------


class CovarianceConfig(BaseModel):
    """Configuration for covariance estimation."""

    model_config = {"frozen": True}

    window: int = 252
    eigenvalue_floor: float = 1e-8
    annualization_factor: float = 252.0


class CovarianceResult(BaseModel):
    """Output from a covariance estimator."""

    model_config = {"frozen": True, "arbitrary_types_allowed": True}

    matrix: np.ndarray  # n×n PSD covariance matrix
    estimator: str  # 'sample' | 'ledoit_wolf' | 'factor_model'
    n_assets: int
    n_observations: int
    condition_number: float
    shrinkage_intensity: float | None  # Only for Ledoit-Wolf
    as_of_ts: datetime


# ---------------------------------------------------------------------------
# Constraint / Relaxation Models
# ---------------------------------------------------------------------------


class RelaxationEvent(BaseModel):
    """Emitted when a constraint is dropped during infeasibility resolution."""

    model_config = {"frozen": True}

    constraint_name: str
    priority: int
    iteration: int  # 1-indexed relaxation step


# ---------------------------------------------------------------------------
# View Schema (Phase 6 integration)
# ---------------------------------------------------------------------------


class View(BaseModel):
    """Structured belief for Black-Litterman."""

    view_id: str
    as_of_ts: datetime
    source: Literal["phase3_signal", "phase6_agent", "manual"]
    P: list[list[float]]  # k×n picking matrix
    Q: list[float]  # k expected return values
    confidence: list[float]  # k confidences in [0.01, 1.0]
    rationale: str
    expires_at: datetime

    @field_validator("confidence")
    @classmethod
    def cap_confidence(cls, v: list[float]) -> list[float]:
        """Cap confidence values at 0.99."""
        return [min(c, 0.99) for c in v]


# ---------------------------------------------------------------------------
# Optimization Context & Result
# ---------------------------------------------------------------------------


class OptContext(BaseModel):
    """Immutable input bag for a single optimization run."""

    model_config = {"frozen": True, "arbitrary_types_allowed": True}

    strategy_id: str
    as_of_ts: datetime
    n_assets: int
    symbols: list[str]
    expected_returns: np.ndarray  # (n,) vector
    covariance: np.ndarray  # (n, n) PSD matrix
    current_weights: np.ndarray  # (n,) prior weights
    prices: np.ndarray  # (n,) current prices
    adv: np.ndarray  # (n,) 30-day ADV in shares
    sector_map: dict[str, str]  # symbol -> GICS L1
    beta: np.ndarray  # (n,) rolling betas vs SPY
    factor_loadings: np.ndarray | None  # (n, k) factor loading matrix
    views: list[View] | None  # BL views (optional)
    scenarios: np.ndarray | None  # (S, n) scenario matrix (CVaR)
    regime_label: str | None
    constraints: list[Any]  # list of Constraint objects (ABC defined elsewhere)
    risk_aversion: float = 5.0
    solver_chain: list[str] = Field(default=["ECOS", "CLARABEL", "SCS"])
    fully_invested: bool = True  # sum(w) = 1 vs sum(w) = 0
    nav: Decimal
    seed: int  # Deterministic seed


class OptResult(BaseModel):
    """Output from a single optimization run."""

    model_config = {"arbitrary_types_allowed": True}

    weights: np.ndarray  # (n,) weight vector
    status: str  # 'optimal', 'optimal_inaccurate', 'infeasible', 'failed'
    solver_used: str | None
    solve_time_ms: float
    objective_value: float | None
    relaxation_events: list[RelaxationEvent] = Field(default_factory=list)
    constraint_diagnostics: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Risk Report Models
# ---------------------------------------------------------------------------


class ScenarioResult(BaseModel):
    """Result from a single stress scenario."""

    scenario_name: ScenarioName
    scenario_version: str
    total_pnl_pct: Decimal  # % of NAV
    factor_contributions: dict[str, Decimal]
    asset_contributions: dict[str, Decimal]
    proxy_estimated_assets: list[str] = Field(default_factory=list)


class ClusterReport(BaseModel):
    """Correlation clustering and concentration metrics."""

    n_clusters: int = 10
    max_cluster_weight: Decimal
    herfindahl_index: Decimal
    effective_n_bets: Decimal
    cluster_assignments: dict[str, int]  # symbol -> cluster_id


class ConstraintDiag(BaseModel):
    """Constraint diagnostic for a solved portfolio."""

    constraint_name: str
    satisfied: bool
    shadow_price: float | None
    slack: float | None
    diagnostic: dict


class PortfolioWeight(BaseModel):
    """Single asset weight in a portfolio."""

    symbol: str = Field(max_length=32)
    weight: Decimal = Field(ge=-1.0, le=1.0)
    sector: str | None = None


# ---------------------------------------------------------------------------
# Published Output Schemas
# ---------------------------------------------------------------------------


class TargetPortfolio(BaseModel):
    """Published portfolio schema — consumed by Phase 7 and Phase 8."""

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
    """Published risk report schema."""

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


# ---------------------------------------------------------------------------
# Rejection Models
# ---------------------------------------------------------------------------


class FailedCheck(BaseModel):
    """A single failed risk gate check."""

    check_name: str
    threshold: float
    actual_value: float


class RiskRejection(BaseModel):
    """Structured rejection record from the risk validation gate."""

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


# ---------------------------------------------------------------------------
# Attribution Models
# ---------------------------------------------------------------------------


class AttributionResult(BaseModel):
    """PnL attribution result (factor or Brinson)."""

    run_id: UUID
    portfolio_id: UUID
    as_of_ts: datetime
    method: Literal["factor_ff5_mom", "brinson"]
    total_pnl_bps: Decimal
    factor_pnl: dict[str, Decimal] | None  # {factor_name: bps}
    idio_pnl_bps: Decimal | None
    sector_pnl: dict[str, Decimal] | None
    created_at: datetime
