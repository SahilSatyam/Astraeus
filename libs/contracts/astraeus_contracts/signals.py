"""Signal output contracts for strategy research engine.

Defines the canonical schema for signal panels produced by backtests
and consumed by downstream phases (Phase 4 portfolio construction,
Phase 7 recommendation engine).

Topic: signals.daily.v1
Key: strategy_id (bytes)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from datetime import date

SIGNAL_SCHEMA_VERSION = 1


class SignalEvent(BaseModel):
    """Daily signal output from a strategy backtest.

    This is the primary interop surface between Phase 3 (strategy research)
    and Phase 4 (portfolio construction) / Phase 7 (recommendation engine).

    The ensembler in Phase 7 consumes `ranked_score` + `confidence`.
    """

    schema_version: int = Field(default=SIGNAL_SCHEMA_VERSION)
    ts: date = Field(..., description="Signal date")
    symbol: str = Field(..., max_length=32, description="Ticker symbol")
    strategy_id: str = Field(..., description="Strategy UUID")
    run_hash: str = Field(..., description="Content-addressable run hash")
    raw_score: float = Field(..., description="Strategy's native score")
    ranked_score: float = Field(
        ..., description="Cross-sectional rank, normalized to [-1, 1]"
    )
    target_weight: float = Field(
        ..., description="Intended portfolio weight, pre-portfolio-construction"
    )
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Strategy-specific confidence [0, 1]"
    )


class BacktestMetricsContract(BaseModel):
    """Standardized metrics output from a backtest run.

    Stored in the backtest_run.metrics JSONB column and exposed via API.
    """

    annualized_return: float
    annualized_vol: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float
    max_dd_duration_days: int
    var_95: float
    cvar_95: float
    hit_ratio: float
    profit_factor: float
    turnover_annual: float
    total_cost_bps: float
    total_trades: int
    total_days: int
    final_equity: float

    # Statistical quality
    probabilistic_sharpe: float = 0.0
    deflated_sharpe: float = 0.0
    sharpe_ci_lower: float = 0.0
    sharpe_ci_upper: float = 0.0
