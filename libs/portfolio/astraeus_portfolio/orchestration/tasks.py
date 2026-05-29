"""Individual Celery tasks for pipeline steps.

Each task is idempotent: keyed on (strategy_id, as_of_date, task_name).
Re-running a completed key returns the prior result from the task_runs table.

Tasks:
1. aggregate_signals — fetch Phase 3 signal batch
2. fetch_prior_portfolio — load previous day's accepted portfolio
3. estimate_covariance — compute covariance matrix
4. estimate_betas — compute rolling betas vs SPY
5. fetch_views — load Phase 6 BL views
6. optimize — run the configured optimizer
7. run_risk_engine — compute full risk report
8. run_risk_gate — binary pass/fail validation
9. publish_portfolio — persist and emit to Redpanda
10. run_attribution — T+1 factor/Brinson attribution
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import structlog

from astraeus_portfolio.contracts import (
    OptContext,
    OptimizerType,
    OptResult,
    RiskReport,
    TargetPortfolio,
)
from astraeus_portfolio.optimizers.fallback import FallbackConfig, FallbackExecutor
from astraeus_portfolio.risk.validation import (
    RiskGate,
    RiskPolicy,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Task result wrapper
# ---------------------------------------------------------------------------


class TaskResult:
    """Wrapper for task execution results with idempotency metadata.

    Attributes:
        task_name: Name of the task.
        strategy_id: Strategy identifier.
        as_of_date: Pipeline date.
        status: 'completed' | 'failed' | 'cached'.
        result_hash: Content hash of the result for determinism checks.
        result: The actual task output.
        duration_ms: Execution time in milliseconds.
    """

    def __init__(
        self,
        task_name: str,
        strategy_id: str,
        as_of_date: date,
        status: str,
        result: Any,
        result_hash: str | None = None,
        duration_ms: float = 0.0,
    ) -> None:
        self.task_name = task_name
        self.strategy_id = strategy_id
        self.as_of_date = as_of_date
        self.status = status
        self.result = result
        self.result_hash = result_hash
        self.duration_ms = duration_ms


def _compute_hash(data: Any) -> str:
    """Compute a deterministic hash of a result for idempotency checks."""
    if isinstance(data, np.ndarray):
        return hashlib.sha256(data.tobytes()).hexdigest()[:16]
    try:
        serialized = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]
    except (TypeError, ValueError):
        return hashlib.sha256(repr(data).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Task: Aggregate Signals
# ---------------------------------------------------------------------------


def task_aggregate_signals(
    strategy_id: str,
    as_of_date: date,
    signal_fetcher: Any = None,
) -> TaskResult:
    """Fetch the Phase 3 signal batch for the given strategy and date.

    Args:
        strategy_id: Strategy identifier.
        as_of_date: The pipeline date.
        signal_fetcher: Callable that returns signal data. In production,
            this reads from the signals table or Redpanda topic.

    Returns:
        TaskResult with signal data as the result.
    """
    start = time.perf_counter()
    logger.info("task_aggregate_signals_start", strategy_id=strategy_id, as_of_date=str(as_of_date))

    try:
        if signal_fetcher is not None:
            signals = signal_fetcher(strategy_id, as_of_date)
        else:
            # Stub: return empty signals when no fetcher provided
            signals = {"symbols": [], "scores": [], "batch_id": str(uuid4())}

        elapsed = (time.perf_counter() - start) * 1000
        return TaskResult(
            task_name="aggregate_signals",
            strategy_id=strategy_id,
            as_of_date=as_of_date,
            status="completed",
            result=signals,
            result_hash=_compute_hash(signals),
            duration_ms=elapsed,
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        logger.error("task_aggregate_signals_failed", error=str(exc), exc_info=True)
        return TaskResult(
            task_name="aggregate_signals",
            strategy_id=strategy_id,
            as_of_date=as_of_date,
            status="failed",
            result={"error": str(exc)},
            duration_ms=elapsed,
        )


# ---------------------------------------------------------------------------
# Task: Fetch Prior Portfolio
# ---------------------------------------------------------------------------


def task_fetch_prior_portfolio(
    strategy_id: str,
    as_of_date: date,
    portfolio_fetcher: Any = None,
) -> TaskResult:
    """Load the previous day's accepted portfolio from the database.

    Args:
        strategy_id: Strategy identifier.
        as_of_date: The pipeline date (fetches portfolio for as_of_date - 1).
        portfolio_fetcher: Callable returning a TargetPortfolio or None.

    Returns:
        TaskResult with the prior TargetPortfolio or None.
    """
    start = time.perf_counter()
    logger.info("task_fetch_prior_portfolio_start", strategy_id=strategy_id)

    try:
        if portfolio_fetcher is not None:
            prior = portfolio_fetcher(strategy_id, as_of_date)
        else:
            prior = None

        elapsed = (time.perf_counter() - start) * 1000
        return TaskResult(
            task_name="fetch_prior_portfolio",
            strategy_id=strategy_id,
            as_of_date=as_of_date,
            status="completed",
            result=prior,
            result_hash=_compute_hash(str(prior)),
            duration_ms=elapsed,
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        logger.error("task_fetch_prior_portfolio_failed", error=str(exc))
        return TaskResult(
            task_name="fetch_prior_portfolio",
            strategy_id=strategy_id,
            as_of_date=as_of_date,
            status="failed",
            result=None,
            duration_ms=elapsed,
        )


# ---------------------------------------------------------------------------
# Task: Estimate Covariance
# ---------------------------------------------------------------------------


def task_estimate_covariance(
    strategy_id: str,
    as_of_date: date,
    returns_matrix: np.ndarray | None = None,
    estimator_type: str = "ledoit_wolf",
) -> TaskResult:
    """Compute the covariance matrix using the configured estimator.

    Args:
        strategy_id: Strategy identifier.
        as_of_date: The pipeline date.
        returns_matrix: (T, n) matrix of historical returns.
        estimator_type: One of 'sample', 'ledoit_wolf', 'factor_model'.

    Returns:
        TaskResult with CovarianceResult as the result.
    """
    start = time.perf_counter()
    logger.info(
        "task_estimate_covariance_start",
        strategy_id=strategy_id,
        estimator=estimator_type,
    )

    try:
        if returns_matrix is None:
            raise ValueError("returns_matrix is required for covariance estimation")

        from astraeus_portfolio.contracts import CovarianceConfig
        from astraeus_portfolio.covariance.base import CovarianceEstimator
        from astraeus_portfolio.covariance.ledoit_wolf import LedoitWolfEstimator
        from astraeus_portfolio.covariance.sample import SampleCovarianceEstimator

        estimators: dict[str, type[CovarianceEstimator]] = {
            "sample": SampleCovarianceEstimator,
            "ledoit_wolf": LedoitWolfEstimator,
        }

        estimator_cls = estimators.get(estimator_type, LedoitWolfEstimator)
        estimator = estimator_cls()
        cov_result = estimator.estimate(returns_matrix, CovarianceConfig())

        elapsed = (time.perf_counter() - start) * 1000
        return TaskResult(
            task_name="estimate_covariance",
            strategy_id=strategy_id,
            as_of_date=as_of_date,
            status="completed",
            result=cov_result,
            result_hash=_compute_hash(cov_result.matrix),
            duration_ms=elapsed,
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        logger.error("task_estimate_covariance_failed", error=str(exc), exc_info=True)
        return TaskResult(
            task_name="estimate_covariance",
            strategy_id=strategy_id,
            as_of_date=as_of_date,
            status="failed",
            result={"error": str(exc)},
            duration_ms=elapsed,
        )


# ---------------------------------------------------------------------------
# Task: Estimate Betas
# ---------------------------------------------------------------------------


def task_estimate_betas(
    strategy_id: str,
    as_of_date: date,
    asset_returns: np.ndarray | None = None,
    market_returns: np.ndarray | None = None,
    window: int = 252,
) -> TaskResult:
    """Compute rolling betas vs SPY for all assets.

    Args:
        strategy_id: Strategy identifier.
        as_of_date: The pipeline date.
        asset_returns: (T, n) matrix of asset returns.
        market_returns: (T,) vector of market (SPY) returns.
        window: Rolling window size (default 252 trading days).

    Returns:
        TaskResult with (n,) beta vector as the result.
    """
    start = time.perf_counter()
    logger.info("task_estimate_betas_start", strategy_id=strategy_id, window=window)

    try:
        if asset_returns is None or market_returns is None:
            raise ValueError("asset_returns and market_returns are required")

        n_assets = asset_returns.shape[1]
        T = min(asset_returns.shape[0], window)

        # Use the most recent `window` observations
        recent_assets = asset_returns[-T:]
        recent_market = market_returns[-T:]

        # OLS beta: cov(r_i, r_m) / var(r_m)
        market_var = np.var(recent_market, ddof=1)
        if market_var < 1e-12:
            betas = np.ones(n_assets)
        else:
            market_demean = recent_market - np.mean(recent_market)
            betas = np.array(
                [
                    np.sum((recent_assets[:, i] - np.mean(recent_assets[:, i])) * market_demean)
                    / ((T - 1) * market_var)
                    for i in range(n_assets)
                ]
            )

        elapsed = (time.perf_counter() - start) * 1000
        return TaskResult(
            task_name="estimate_betas",
            strategy_id=strategy_id,
            as_of_date=as_of_date,
            status="completed",
            result=betas,
            result_hash=_compute_hash(betas),
            duration_ms=elapsed,
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        logger.error("task_estimate_betas_failed", error=str(exc), exc_info=True)
        return TaskResult(
            task_name="estimate_betas",
            strategy_id=strategy_id,
            as_of_date=as_of_date,
            status="failed",
            result={"error": str(exc)},
            duration_ms=elapsed,
        )


# ---------------------------------------------------------------------------
# Task: Fetch Views
# ---------------------------------------------------------------------------


def task_fetch_views(
    strategy_id: str,
    as_of_date: date,
    view_fetcher: Any = None,
) -> TaskResult:
    """Load Phase 6 Black-Litterman views.

    Args:
        strategy_id: Strategy identifier.
        as_of_date: The pipeline date.
        view_fetcher: Callable returning a list of View objects.

    Returns:
        TaskResult with list of View objects (may be empty).
    """
    start = time.perf_counter()
    logger.info("task_fetch_views_start", strategy_id=strategy_id)

    try:
        if view_fetcher is not None:
            views = view_fetcher(strategy_id, as_of_date)
        else:
            views = []

        elapsed = (time.perf_counter() - start) * 1000
        return TaskResult(
            task_name="fetch_views",
            strategy_id=strategy_id,
            as_of_date=as_of_date,
            status="completed",
            result=views,
            result_hash=_compute_hash(str(views)),
            duration_ms=elapsed,
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        logger.error("task_fetch_views_failed", error=str(exc))
        return TaskResult(
            task_name="fetch_views",
            strategy_id=strategy_id,
            as_of_date=as_of_date,
            status="failed",
            result=[],
            duration_ms=elapsed,
        )


# ---------------------------------------------------------------------------
# Task: Optimize
# ---------------------------------------------------------------------------


def task_optimize(
    strategy_id: str,
    as_of_date: date,
    ctx: OptContext,
    optimizer_type: OptimizerType = OptimizerType.MVO,
) -> TaskResult:
    """Run the configured optimizer on the prepared OptContext.

    Args:
        strategy_id: Strategy identifier.
        as_of_date: The pipeline date.
        ctx: Fully populated optimization context.
        optimizer_type: Which optimizer to use.

    Returns:
        TaskResult with OptResult as the result.
    """
    start = time.perf_counter()
    logger.info(
        "task_optimize_start",
        strategy_id=strategy_id,
        optimizer=optimizer_type,
        n_assets=ctx.n_assets,
    )

    try:
        from astraeus_portfolio.optimizers.black_litterman import BlackLittermanOptimizer
        from astraeus_portfolio.optimizers.cvar import CVaROptimizer
        from astraeus_portfolio.optimizers.mvo import MeanVarianceOptimizer
        from astraeus_portfolio.optimizers.risk_parity import RiskParityOptimizer

        optimizer_map = {
            OptimizerType.MVO: MeanVarianceOptimizer,
            OptimizerType.BLACK_LITTERMAN: BlackLittermanOptimizer,
            OptimizerType.RISK_PARITY: RiskParityOptimizer,
            OptimizerType.CVAR: CVaROptimizer,
        }

        optimizer_cls = optimizer_map[optimizer_type]
        optimizer = optimizer_cls()
        result: OptResult = optimizer.run(ctx)

        elapsed = (time.perf_counter() - start) * 1000
        return TaskResult(
            task_name="optimize",
            strategy_id=strategy_id,
            as_of_date=as_of_date,
            status="completed" if result.status in ("optimal", "optimal_inaccurate") else "failed",
            result=result,
            result_hash=_compute_hash(result.weights) if result.weights.size > 0 else None,
            duration_ms=elapsed,
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        logger.error("task_optimize_failed", error=str(exc), exc_info=True)
        return TaskResult(
            task_name="optimize",
            strategy_id=strategy_id,
            as_of_date=as_of_date,
            status="failed",
            result={"error": str(exc)},
            duration_ms=elapsed,
        )


# ---------------------------------------------------------------------------
# Task: Risk Gate
# ---------------------------------------------------------------------------


def task_run_risk_gate(
    strategy_id: str,
    as_of_date: date,
    portfolio: TargetPortfolio,
    risk_report: RiskReport,
    policy: RiskPolicy,
) -> TaskResult:
    """Run the binary risk validation gate.

    Args:
        strategy_id: Strategy identifier.
        as_of_date: The pipeline date.
        portfolio: The candidate portfolio.
        risk_report: The computed risk report.
        policy: The active risk policy.

    Returns:
        TaskResult with ValidationResult as the result.
    """
    start = time.perf_counter()
    logger.info("task_run_risk_gate_start", strategy_id=strategy_id)

    try:
        gate = RiskGate()
        validation = gate.validate(portfolio, risk_report, policy)

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "task_run_risk_gate_complete",
            strategy_id=strategy_id,
            status=validation.status,
            n_failed_checks=len(validation.failed_checks),
        )

        return TaskResult(
            task_name="risk_gate",
            strategy_id=strategy_id,
            as_of_date=as_of_date,
            status="completed",
            result=validation,
            result_hash=_compute_hash(validation.status),
            duration_ms=elapsed,
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        logger.error("task_run_risk_gate_failed", error=str(exc), exc_info=True)
        return TaskResult(
            task_name="risk_gate",
            strategy_id=strategy_id,
            as_of_date=as_of_date,
            status="failed",
            result={"error": str(exc)},
            duration_ms=elapsed,
        )


# ---------------------------------------------------------------------------
# Task: Apply Fallback
# ---------------------------------------------------------------------------


def task_apply_fallback(
    strategy_id: str,
    as_of_date: date,
    fallback_config: FallbackConfig,
    nav: Decimal,
    prior_portfolio: TargetPortfolio | None = None,
    rejection_id: UUID | None = None,
    risk_report_id: UUID | None = None,
) -> TaskResult:
    """Apply the configured fallback action after a risk rejection.

    Args:
        strategy_id: Strategy identifier.
        as_of_date: The pipeline date.
        fallback_config: The strategy's fallback configuration.
        nav: Current NAV.
        prior_portfolio: Previous day's portfolio (for hold_prior).
        rejection_id: UUID of the rejection record.
        risk_report_id: UUID of the risk report.

    Returns:
        TaskResult with FallbackOutcome as the result.
    """
    start = time.perf_counter()
    logger.info(
        "task_apply_fallback_start",
        strategy_id=strategy_id,
        action=fallback_config.action,
    )

    try:
        executor = FallbackExecutor()
        outcome = executor.execute(
            config=fallback_config,
            strategy_id=strategy_id,
            as_of_ts=datetime.combine(as_of_date, datetime.min.time()),
            nav=nav,
            prior_portfolio=prior_portfolio,
            rejection_id=rejection_id,
            risk_report_id=risk_report_id,
        )

        elapsed = (time.perf_counter() - start) * 1000
        return TaskResult(
            task_name="apply_fallback",
            strategy_id=strategy_id,
            as_of_date=as_of_date,
            status="completed",
            result=outcome,
            result_hash=_compute_hash(outcome.action_taken),
            duration_ms=elapsed,
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        logger.error("task_apply_fallback_failed", error=str(exc), exc_info=True)
        return TaskResult(
            task_name="apply_fallback",
            strategy_id=strategy_id,
            as_of_date=as_of_date,
            status="failed",
            result={"error": str(exc)},
            duration_ms=elapsed,
        )
