"""Structured output schemas for all agents.

Every agent output crossing a service boundary MUST be one of these
Pydantic models. Free-text only inside an agent's scratchpad.

Schema versioning: breaking changes bump the version suffix (v1 → v2).
Phase 7 and Phase 9 declare which schema versions they accept.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# --- Shared primitives ---


class Citation(BaseModel):
    """The only valid form of evidence in any agent output."""

    chunk_id: str
    source_type: Literal["filing", "news", "transcript", "social", "feature", "backtest"]
    source_id: str
    span: tuple[int, int] = (0, 0)
    quoted_text: str = Field(default="", max_length=400)
    url: str | None = None


# --- Research Agent ---


class ResearchFinding(BaseModel):
    claim: str = Field(max_length=400)
    citations: list[Citation] = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]
    contradicts: list[str] = Field(default_factory=list)


class ResearchOutput(BaseModel):
    """v1 — Research agent structured output."""

    schema_version: str = "v1"
    ticker: str
    as_of: datetime
    summary: str = Field(max_length=1500)
    findings: list[ResearchFinding] = Field(min_length=1, max_length=10)
    open_questions: list[str] = Field(default_factory=list)


# --- Sentiment Agent ---


class SentimentNarrative(BaseModel):
    """v1 — Sentiment agent structured output."""

    schema_version: str = "v1"
    ticker: str
    as_of: datetime
    score: float | None = None  # from Phase 5, not invented
    score_delta: float | None = None
    drivers: list[ResearchFinding] = Field(default_factory=list)
    divergence_flags: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


# --- Strategy Agent ---


class StrategyMatch(BaseModel):
    strategy_id: str
    strategy_version: str
    current_signal: float | None = None
    signal_as_of: datetime | None = None
    fit_rationale: str = ""
    decay_flag: bool = False
    decay_evidence: list[Citation] = Field(default_factory=list)


class StrategyOutput(BaseModel):
    """v1 — Strategy agent structured output."""

    schema_version: str = "v1"
    ticker: str
    as_of: datetime
    matches: list[StrategyMatch] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    narrative: str = ""


# --- Risk Agent ---


class RiskCheckResult(BaseModel):
    check_name: str
    passed: bool
    value: float | None = None
    threshold: float | None = None
    detail: str = ""


class RiskBreach(BaseModel):
    check_name: str
    severity: Literal["warning", "critical"]
    value: float
    threshold: float
    narrative: str = ""


class StressResult(BaseModel):
    scenario_name: str
    portfolio_pnl: float
    worst_position: str | None = None
    detail: str = ""


class RiskAssessment(BaseModel):
    """v1 — Risk agent structured output."""

    schema_version: str = "v1"
    as_of: datetime
    checks: list[RiskCheckResult] = Field(default_factory=list)
    breaches: list[RiskBreach] = Field(default_factory=list)
    stress_results: list[StressResult] = Field(default_factory=list)
    narrative: str = ""
    hitl_required: bool = False
    hitl_reason: str | None = None


# --- Execution Agent ---


class ExecutionAdvice(BaseModel):
    """v1 — Execution agent structured output. Advisory only in Phase 6."""

    schema_version: str = "v1"
    algo: Literal["TWAP", "VWAP", "IS", "POV", "MARKET"]
    slicing_horizon_minutes: int = 30
    participation_rate_max: float = 0.05
    caveats: list[str] = Field(default_factory=list)
    requires_human_execution: Literal[True] = True  # always True in Phase 6


# --- Portfolio Agent ---


class PortfolioCommentary(BaseModel):
    """v1 — Portfolio agent structured output."""

    schema_version: str = "v1"
    as_of: datetime
    total_value: float | None = None
    top_exposures: list[dict[str, object]] = Field(default_factory=list)
    rebalance_suggestions: list[str] = Field(default_factory=list)
    narrative: str = ""
    citations: list[Citation] = Field(default_factory=list)


# --- Compliance Agent ---


class ComplianceResult(BaseModel):
    """v1 — Compliance agent structured output."""

    schema_version: str = "v1"
    approved: bool = True
    flags: list[str] = Field(default_factory=list)
    redactions_applied: list[str] = Field(default_factory=list)
    audit_notes: str = ""


# --- Composite workflow outputs ---


class TradeThesisOutput(BaseModel):
    """v1 — Full trade thesis workflow output."""

    schema_version: str = "v1"
    ticker: str
    as_of: datetime
    research: ResearchOutput
    sentiment: SentimentNarrative
    strategy: StrategyOutput
    risk: RiskAssessment
    compliance: ComplianceResult
    confidence_rationale: str = ""
    contrarian_points: list[str] = Field(default_factory=list)


class DailyBriefOutput(BaseModel):
    """v1 — Daily market brief workflow output."""

    schema_version: str = "v1"
    as_of: datetime
    macro_summary: str = ""
    sector_highlights: list[dict[str, object]] = Field(default_factory=list)
    research: ResearchOutput | None = None
    sentiment: SentimentNarrative | None = None
    risk: RiskAssessment | None = None
    compliance: ComplianceResult | None = None
