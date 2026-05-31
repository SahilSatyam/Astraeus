"""Inter-stage contracts for the recommendation pipeline.

Each stage produces a typed output that the next stage consumes.
These are the rigid boundaries that make stages independently testable and replaceable.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RunStatus(StrEnum):
    """Pipeline run lifecycle status."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    DEGRADED = "degraded"
    FAILED = "failed"


class RecommendationState(StrEnum):
    """Recommendation lifecycle state machine."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    OVERRIDDEN = "overridden"
    EXPIRED = "expired"


class Side(StrEnum):
    """Trade direction."""

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class DecisionType(StrEnum):
    """HITL decision types."""

    APPROVE = "approve"
    REJECT = "reject"
    OVERRIDE = "override"


class RegimeLabel(StrEnum):
    """Market regime labels from the HMM/GMM detector."""

    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"
    VOL_SPIKE = "vol_spike"
    MEAN_REVERSION = "mean_reversion"
    TRENDING = "trending"
    UNCERTAIN = "uncertain"


class SignalName(StrEnum):
    """Canonical signal generator names."""

    TECHNICAL = "technical"
    STATISTICAL = "statistical"
    ML_XGB = "ml_xgb"
    NLP_SENTIMENT = "nlp_sentiment"
    MACRO = "macro"


# ---------------------------------------------------------------------------
# Stage 1: Aggregator Output
# ---------------------------------------------------------------------------


class DailyInputSnapshot(BaseModel):
    """Output of Stage 1 — the immutable input snapshot for the day's run."""

    run_id: UUID = Field(default_factory=uuid4)
    run_date: date
    snapshot_hash: str = Field(..., description="SHA-256 of the serialized feature matrix")
    symbols: list[str]
    feature_names: list[str]
    feature_matrix: dict[str, dict[str, float | None]] = Field(
        ..., description="symbol -> {feature_name: value}"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())


# ---------------------------------------------------------------------------
# Stage 2: Regime Detector Output
# ---------------------------------------------------------------------------


class RegimeDetection(BaseModel):
    """Output of Stage 2 — current market regime classification."""

    run_id: UUID
    label: RegimeLabel
    probability: float = Field(..., ge=0.0, le=1.0)
    stability_days: int = Field(..., ge=0, description="Consecutive days at this label")
    model: str = Field(default="hmm_v1")
    hmm_state_probs: dict[str, float] = Field(
        default_factory=dict, description="All state probabilities from HMM"
    )
    gmm_cluster: str | None = Field(
        default=None, description="GMM cross-validation cluster label"
    )
    detected_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())


# ---------------------------------------------------------------------------
# Stage 3: Signal Generator Output
# ---------------------------------------------------------------------------


class SignalValue(BaseModel):
    """Single signal output for one ticker."""

    ticker: str
    score: float = Field(..., description="Raw signal score")
    score_z: float | None = Field(default=None, description="Cross-sectional z-score")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class SignalOutput(BaseModel):
    """Output of a single signal generator (one of 5)."""

    run_id: UUID
    signal: SignalName
    values: list[SignalValue]
    compute_time_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stage 4: Ensemble Output
# ---------------------------------------------------------------------------


class EnsembleCandidate(BaseModel):
    """A ranked candidate from the ensemble stage."""

    ticker: str
    composite_score: float
    rank: int
    component_attribution: dict[str, float] = Field(
        ..., description="signal_name -> contribution to composite score"
    )


class EnsembleOutput(BaseModel):
    """Output of Stage 4 — ranked candidates with attribution."""

    run_id: UUID
    regime: RegimeLabel
    candidates: list[EnsembleCandidate] = Field(
        ..., description="Sorted by rank ascending (1 = best)"
    )
    weights_used: dict[str, float] = Field(
        ..., description="signal_name -> weight applied for this regime"
    )


# ---------------------------------------------------------------------------
# Stage 5: Portfolio Construction Output
# ---------------------------------------------------------------------------


class PortfolioAllocation(BaseModel):
    """Single allocation from portfolio construction."""

    ticker: str
    side: Side
    target_weight: float = Field(..., ge=-1.0, le=1.0)


class PortfolioOutput(BaseModel):
    """Output of Stage 5 — sized positions from the optimizer."""

    run_id: UUID
    allocations: list[PortfolioAllocation]
    optimizer_used: str
    solve_time_ms: float = 0.0


# ---------------------------------------------------------------------------
# Stage 6: Risk Validation Output
# ---------------------------------------------------------------------------


class RiskCheckResult(BaseModel):
    """Result of a single risk check."""

    rule: str
    passed: bool
    detail: dict[str, Any] = Field(default_factory=dict)


class RiskValidationOutput(BaseModel):
    """Output of Stage 6 — risk gate results per allocation."""

    run_id: UUID
    passed_allocations: list[PortfolioAllocation]
    rejected_allocations: list[PortfolioAllocation] = Field(default_factory=list)
    checks: list[RiskCheckResult] = Field(default_factory=list)
    all_passed: bool = True


# ---------------------------------------------------------------------------
# Stage 7: Thesis Output
# ---------------------------------------------------------------------------


class ThesisOutput(BaseModel):
    """Output of Stage 7 — AI-generated thesis per recommendation."""

    run_id: UUID
    ticker: str
    thesis_run_id: UUID | None = Field(
        default=None, description="Phase 6 agent_run ID for full thesis"
    )
    summary: str = Field(default="", description="Short thesis summary")
    citations: list[str] = Field(default_factory=list)
    generated: bool = True


# ---------------------------------------------------------------------------
# Stage 8: HITL / Final Recommendation
# ---------------------------------------------------------------------------


class Recommendation(BaseModel):
    """Final recommendation awaiting HITL decision."""

    rec_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    ticker: str
    side: Side
    target_weight: float
    rank: int
    composite_score: float
    component_attribution: dict[str, float]
    risk_passed: bool
    risk_notes: dict[str, Any] | None = None
    thesis_run_id: UUID | None = None
    thesis_summary: str = ""
    state: RecommendationState = RecommendationState.PROPOSED
    horizon_days: int = 60
    created_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())


class RecommendationDecision(BaseModel):
    """HITL decision on a recommendation."""

    rec_id: UUID
    decided_by: str = "operator"
    decided_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    decision: DecisionType
    override_weight: float | None = None
    rationale: str = ""


# ---------------------------------------------------------------------------
# Pipeline Run Envelope
# ---------------------------------------------------------------------------


class PipelineRun(BaseModel):
    """Top-level run envelope tracking the full pipeline execution."""

    run_id: UUID = Field(default_factory=uuid4)
    run_date: date
    status: RunStatus = RunStatus.QUEUED
    started_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    finished_at: datetime | None = None
    input_snapshot_hash: str = ""
    code_commit: str = ""
    notes: str = ""
    stage_timings: dict[str, float] = Field(
        default_factory=dict, description="stage_name -> duration_seconds"
    )
    failed_stages: list[str] = Field(default_factory=list)
