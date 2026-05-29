"""Astraeus strategy research engine.

Provides:
- Strategy protocol and data types
- Vectorized and event-driven backtesting engines
- Transaction cost model (commission, spread, impact, slippage)
- Metrics module (Sharpe, Sortino, drawdown, VaR, deflated Sharpe)
- Walk-forward harness with purge + embargo
- Monte Carlo simulation (bootstrap + parameter perturbation)
- Reconciliation harness (vectorized vs event-driven)
- Factor attribution (FF3 + Carhart)
- Strategy registry for content-addressable runs
"""

from astraeus_strategy.attribution import AttributionResult, compute_attribution
from astraeus_strategy.cost_model import CostModel
from astraeus_strategy.engines.event_driven import EventDrivenEngine, EventDrivenResult
from astraeus_strategy.engines.vectorized import VectorizedEngine, VectorizedResult
from astraeus_strategy.metrics import BacktestMetrics, compute_metrics
from astraeus_strategy.monte_carlo import MonteCarloResult, bootstrap_returns, parameter_perturbation
from astraeus_strategy.protocol import Strategy, StrategyContext
from astraeus_strategy.reconciliation import ReconciliationResult, reconcile
from astraeus_strategy.registry import BacktestRun, StrategyEntry, compute_run_hash
from astraeus_strategy.types import (
    BacktestConfig,
    Bar,
    DataDependency,
    FeatureRef,
    Fill,
    Order,
    OrderType,
    PortfolioState,
    Position,
    Side,
    Signal,
    Target,
    UniverseRef,
)
from astraeus_strategy.walk_forward import (
    WalkForwardConfig,
    WalkForwardResult,
    WalkForwardWindow,
    generate_windows,
    purged_kfold_splits,
)

__all__ = [
    "AttributionResult",
    "BacktestConfig",
    "BacktestMetrics",
    "BacktestRun",
    "Bar",
    "CostModel",
    "DataDependency",
    "EventDrivenEngine",
    "EventDrivenResult",
    "FeatureRef",
    "Fill",
    "MonteCarloResult",
    "Order",
    "OrderType",
    "PortfolioState",
    "Position",
    "ReconciliationResult",
    "Side",
    "Signal",
    "Strategy",
    "StrategyContext",
    "StrategyEntry",
    "Target",
    "UniverseRef",
    "VectorizedEngine",
    "VectorizedResult",
    "WalkForwardConfig",
    "WalkForwardResult",
    "WalkForwardWindow",
    "bootstrap_returns",
    "compute_attribution",
    "compute_metrics",
    "compute_run_hash",
    "generate_windows",
    "parameter_perturbation",
    "purged_kfold_splits",
    "reconcile",
]
