"""Reconciliation harness — compares vectorized vs event-driven engines.

Runs both engines on the same strategy with the same data and seed,
then checks that metrics agree within the defined tolerance band.

Tolerance (from Phase 3 plan):
- Annualized return: <= 30 bps absolute deviation
- Annualized Sharpe: <= 0.15 absolute deviation
- Max drawdown: <= 100 bps absolute deviation
- Turnover: <= 5% relative deviation

Two acceptable causes for divergence:
1. Cost model headroom (event-driven applies depth-conditional impact)
2. Fill timing (event-driven respects partial fills and halts)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from astraeus_strategy.metrics import BacktestMetrics

logger = structlog.get_logger("astraeus.strategy.reconciliation")


@dataclass(frozen=True, slots=True)
class ToleranceBand:
    """Acceptable deviation between engines."""

    return_bps: float = 30.0  # 30 bps absolute
    sharpe_abs: float = 0.15  # 0.15 absolute
    max_dd_bps: float = 100.0  # 100 bps absolute
    turnover_pct: float = 5.0  # 5% relative


@dataclass(slots=True)
class ReconciliationCheck:
    """Result of a single metric comparison."""

    metric_name: str
    vectorized_value: float
    event_driven_value: float
    deviation: float
    tolerance: float
    passed: bool
    explanation: str = ""


@dataclass(slots=True)
class ReconciliationResult:
    """Full reconciliation report."""

    strategy_name: str
    checks: list[ReconciliationCheck] = field(default_factory=list)
    passed: bool = True
    summary: str = ""

    @property
    def failed_checks(self) -> list[ReconciliationCheck]:
        return [c for c in self.checks if not c.passed]


def reconcile(
    strategy_name: str,
    vectorized_metrics: BacktestMetrics,
    event_driven_metrics: BacktestMetrics,
    tolerance: ToleranceBand | None = None,
) -> ReconciliationResult:
    """Compare metrics from both engines and produce a reconciliation report.

    Args:
        strategy_name: Name of the strategy being reconciled.
        vectorized_metrics: Metrics from the vectorized engine.
        event_driven_metrics: Metrics from the event-driven engine.
        tolerance: Acceptable deviation band (uses defaults if None).

    Returns:
        ReconciliationResult with pass/fail status and detailed checks.
    """
    if tolerance is None:
        tolerance = ToleranceBand()

    result = ReconciliationResult(strategy_name=strategy_name)

    # Check annualized return (bps)
    ret_dev = (
        abs(vectorized_metrics.annualized_return - event_driven_metrics.annualized_return) * 10_000
    )
    result.checks.append(
        ReconciliationCheck(
            metric_name="annualized_return",
            vectorized_value=vectorized_metrics.annualized_return,
            event_driven_value=event_driven_metrics.annualized_return,
            deviation=ret_dev,
            tolerance=tolerance.return_bps,
            passed=ret_dev <= tolerance.return_bps,
            explanation=f"Deviation: {ret_dev:.1f} bps (limit: {tolerance.return_bps} bps)",
        )
    )

    # Check Sharpe ratio (absolute)
    sharpe_dev = abs(vectorized_metrics.sharpe - event_driven_metrics.sharpe)
    result.checks.append(
        ReconciliationCheck(
            metric_name="sharpe",
            vectorized_value=vectorized_metrics.sharpe,
            event_driven_value=event_driven_metrics.sharpe,
            deviation=sharpe_dev,
            tolerance=tolerance.sharpe_abs,
            passed=sharpe_dev <= tolerance.sharpe_abs,
            explanation=f"Deviation: {sharpe_dev:.3f} (limit: {tolerance.sharpe_abs})",
        )
    )

    # Check max drawdown (bps)
    dd_dev = abs(vectorized_metrics.max_drawdown - event_driven_metrics.max_drawdown) * 10_000
    result.checks.append(
        ReconciliationCheck(
            metric_name="max_drawdown",
            vectorized_value=vectorized_metrics.max_drawdown,
            event_driven_value=event_driven_metrics.max_drawdown,
            deviation=dd_dev,
            tolerance=tolerance.max_dd_bps,
            passed=dd_dev <= tolerance.max_dd_bps,
            explanation=f"Deviation: {dd_dev:.1f} bps (limit: {tolerance.max_dd_bps} bps)",
        )
    )

    # Check turnover (relative %)
    vec_turnover = vectorized_metrics.turnover_annual
    ed_turnover = event_driven_metrics.turnover_annual
    if vec_turnover > 0:
        turnover_dev = abs(vec_turnover - ed_turnover) / vec_turnover * 100
    else:
        turnover_dev = 0.0

    result.checks.append(
        ReconciliationCheck(
            metric_name="turnover",
            vectorized_value=vec_turnover,
            event_driven_value=ed_turnover,
            deviation=turnover_dev,
            tolerance=tolerance.turnover_pct,
            passed=turnover_dev <= tolerance.turnover_pct,
            explanation=f"Relative deviation: {turnover_dev:.1f}% (limit: {tolerance.turnover_pct}%)",
        )
    )

    # Overall pass/fail
    result.passed = all(c.passed for c in result.checks)

    if result.passed:
        result.summary = f"PASS: {strategy_name} — all metrics within tolerance"
    else:
        failed = [c.metric_name for c in result.failed_checks]
        result.summary = f"FAIL: {strategy_name} — exceeded tolerance on: {', '.join(failed)}"

    logger.info(
        "reconciliation_complete",
        strategy=strategy_name,
        passed=result.passed,
        checks_failed=len(result.failed_checks),
    )

    return result
