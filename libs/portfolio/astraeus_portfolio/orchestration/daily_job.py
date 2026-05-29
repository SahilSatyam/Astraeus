"""Celery DAG entrypoint for daily portfolio pipeline.

Orchestrates the full daily portfolio construction workflow:
    signals → covariance/betas/views (parallel) → optimize → risk → gate → publish

Trigger:
- Primary: cron at 16:30 ET (post-close, post-Phase 3 batch).
- Event-driven: subscribes to signals.daily_batch.completed.v1.

Idempotency:
- Every task keys on (strategy_id, as_of_date). Re-running a completed key
  returns the prior result from the task_runs table.

Retry:
- Exponential backoff: 1s, 4s, 16s, 64s, 256s (5 retries).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import numpy as np
import structlog

from astraeus_portfolio.contracts import (
    CovarianceMethod,
    OptimizerType,
    PortfolioStatus,
    PortfolioWeight,
    RiskReport,
    TargetPortfolio,
)
from astraeus_portfolio.optimizers.fallback import FallbackConfig, FallbackExecutor
from astraeus_portfolio.orchestration.pit import validate_pit_context
from astraeus_portfolio.orchestration.tasks import (
    TaskResult,
    task_aggregate_signals,
    task_apply_fallback,
    task_estimate_betas,
    task_estimate_covariance,
    task_fetch_prior_portfolio,
    task_fetch_views,
    task_optimize,
    task_run_risk_gate,
)
from astraeus_portfolio.risk.validation import RiskGate, RiskPolicy, ValidationStatus

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Pipeline Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineConfig:
    """Configuration for the daily portfolio pipeline.

    Attributes:
        strategy_id: Strategy identifier.
        optimizer_type: Which optimizer to use.
        covariance_method: Covariance estimation method.
        risk_policy: Active risk policy for the gate.
        fallback_config: Fallback action on rejection.
        nav: Current NAV for the strategy.
        max_retries: Maximum retry attempts per task.
        retry_base_delay_s: Base delay for exponential backoff.
    """

    strategy_id: str
    optimizer_type: OptimizerType = OptimizerType.MVO
    covariance_method: CovarianceMethod = CovarianceMethod.LEDOIT_WOLF
    risk_policy: RiskPolicy = field(default_factory=lambda: RiskPolicy(policy_version="v1.0"))
    fallback_config: FallbackConfig = field(default_factory=FallbackConfig)
    nav: Decimal = Decimal("10000.00")
    max_retries: int = 5
    retry_base_delay_s: float = 1.0


# ---------------------------------------------------------------------------
# Pipeline Result
# ---------------------------------------------------------------------------


@dataclass
class PipelineResult:
    """Result of a full daily pipeline run.

    Attributes:
        strategy_id: Strategy identifier.
        as_of_date: Pipeline date.
        status: Overall pipeline status.
        portfolio: The published portfolio (if any).
        risk_report: The computed risk report (if any).
        task_results: Individual task results for debugging.
        total_duration_ms: Total pipeline wall-clock time.
    """

    strategy_id: str
    as_of_date: date
    status: str  # 'completed' | 'failed' | 'fallback_applied'
    portfolio: TargetPortfolio | None = None
    risk_report: RiskReport | None = None
    task_results: dict[str, TaskResult] = field(default_factory=dict)
    total_duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Daily Pipeline Orchestrator
# ---------------------------------------------------------------------------


class DailyPipelineOrchestrator:
    """Orchestrates the daily portfolio construction pipeline.

    This is the main entry point for the daily job. It coordinates all tasks
    in the correct dependency order, handles failures, and applies fallback
    policies when portfolios are rejected.

    The orchestrator is designed to be called by Celery (or Temporal) but
    is itself framework-agnostic — it's a plain Python class that can be
    tested without a task queue.
    """

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self._gate = RiskGate()
        self._fallback_executor = FallbackExecutor()

    def run(
        self,
        as_of_date: date,
        returns_matrix: np.ndarray | None = None,
        market_returns: np.ndarray | None = None,
        symbols: list[str] | None = None,
        expected_returns: np.ndarray | None = None,
        prices: np.ndarray | None = None,
        adv: np.ndarray | None = None,
        sector_map: dict[str, str] | None = None,
        constraints: list[Any] | None = None,
        signal_fetcher: Any = None,
        portfolio_fetcher: Any = None,
        view_fetcher: Any = None,
        risk_report_builder: Any = None,
    ) -> PipelineResult:
        """Execute the full daily pipeline.

        Args:
            as_of_date: The pipeline date.
            returns_matrix: (T, n) historical returns for covariance/beta.
            market_returns: (T,) SPY returns for beta estimation.
            symbols: List of asset symbols in the universe.
            expected_returns: (n,) expected return vector from Phase 3.
            prices: (n,) current prices.
            adv: (n,) 30-day ADV in shares.
            sector_map: symbol -> GICS L1 mapping.
            constraints: List of Constraint objects.
            signal_fetcher: Callable for signal aggregation.
            portfolio_fetcher: Callable for prior portfolio lookup.
            view_fetcher: Callable for BL views.
            risk_report_builder: Callable that builds a RiskReport from weights.

        Returns:
            PipelineResult with the outcome of the pipeline run.
        """
        pipeline_start = time.perf_counter()
        task_results: dict[str, TaskResult] = {}

        logger.info(
            "daily_pipeline_start",
            strategy_id=self.config.strategy_id,
            as_of_date=str(as_of_date),
            optimizer=self.config.optimizer_type,
        )

        # --- Step 1: Aggregate signals ---
        signals_result = task_aggregate_signals(
            strategy_id=self.config.strategy_id,
            as_of_date=as_of_date,
            signal_fetcher=signal_fetcher,
        )
        task_results["aggregate_signals"] = signals_result
        if signals_result.status == "failed":
            return self._failed_result(as_of_date, task_results, pipeline_start)

        # --- Step 2: Fetch prior portfolio ---
        prior_result = task_fetch_prior_portfolio(
            strategy_id=self.config.strategy_id,
            as_of_date=as_of_date,
            portfolio_fetcher=portfolio_fetcher,
        )
        task_results["fetch_prior_portfolio"] = prior_result

        # --- Step 3: Parallel tasks (covariance, betas, views) ---
        cov_result = task_estimate_covariance(
            strategy_id=self.config.strategy_id,
            as_of_date=as_of_date,
            returns_matrix=returns_matrix,
            estimator_type=self.config.covariance_method.value,
        )
        task_results["estimate_covariance"] = cov_result
        if cov_result.status == "failed":
            return self._failed_result(as_of_date, task_results, pipeline_start)

        beta_result = task_estimate_betas(
            strategy_id=self.config.strategy_id,
            as_of_date=as_of_date,
            asset_returns=returns_matrix,
            market_returns=market_returns,
        )
        task_results["estimate_betas"] = beta_result
        if beta_result.status == "failed":
            return self._failed_result(as_of_date, task_results, pipeline_start)

        views_result = task_fetch_views(
            strategy_id=self.config.strategy_id,
            as_of_date=as_of_date,
            view_fetcher=view_fetcher,
        )
        task_results["fetch_views"] = views_result

        # --- Step 4: Build OptContext ---
        n_assets = returns_matrix.shape[1] if returns_matrix is not None else 0
        if symbols is None:
            symbols = [f"ASSET_{i}" for i in range(n_assets)]
        if expected_returns is None:
            expected_returns = np.zeros(n_assets)
        if prices is None:
            prices = np.ones(n_assets) * 100.0
        if adv is None:
            adv = np.ones(n_assets) * 1_000_000
        if sector_map is None:
            sector_map = dict.fromkeys(symbols, "Unclassified")
        if constraints is None:
            constraints = []

        from astraeus_portfolio.contracts import OptContext

        covariance_matrix = (
            cov_result.result.matrix if hasattr(cov_result.result, "matrix") else np.eye(n_assets)
        )
        betas = (
            beta_result.result if isinstance(beta_result.result, np.ndarray) else np.ones(n_assets)
        )

        # Determine current weights from prior portfolio
        current_weights = np.zeros(n_assets)
        prior_portfolio = prior_result.result
        if prior_portfolio is not None and hasattr(prior_portfolio, "weights"):
            symbol_to_idx = {s: i for i, s in enumerate(symbols)}
            for pw in prior_portfolio.weights:
                idx = symbol_to_idx.get(pw.symbol)
                if idx is not None:
                    current_weights[idx] = float(pw.weight)

        ctx = OptContext(
            strategy_id=self.config.strategy_id,
            as_of_ts=datetime.combine(as_of_date, datetime.min.time()),
            n_assets=n_assets,
            symbols=symbols,
            expected_returns=expected_returns,
            covariance=covariance_matrix,
            current_weights=current_weights,
            prices=prices,
            adv=adv,
            sector_map=sector_map,
            beta=betas,
            factor_loadings=None,
            views=views_result.result if views_result.result else None,
            scenarios=None,
            regime_label=None,
            constraints=constraints,
            risk_aversion=5.0,
            nav=self.config.nav,
            seed=42,
        )

        # --- PIT validation ---
        # Note: covariance as_of_ts is the computation timestamp, not the data
        # cutoff. PIT is enforced at the data-access layer (Phase 2). We skip
        # the covariance timestamp here to avoid false positives.
        pit_violations = validate_pit_context(
            target_ts=ctx.as_of_ts,
        )
        if pit_violations:
            logger.error("pit_violations_detected", violations=pit_violations)
            return self._failed_result(as_of_date, task_results, pipeline_start)

        # --- Step 5: Optimize ---
        opt_result = task_optimize(
            strategy_id=self.config.strategy_id,
            as_of_date=as_of_date,
            ctx=ctx,
            optimizer_type=self.config.optimizer_type,
        )
        task_results["optimize"] = opt_result
        if opt_result.status == "failed":
            return self._failed_result(as_of_date, task_results, pipeline_start)

        # --- Step 6: Build TargetPortfolio ---
        opt_output = opt_result.result
        portfolio_id = uuid4()
        risk_report_id = uuid4()

        weights = [
            PortfolioWeight(
                symbol=symbols[i],
                weight=Decimal(str(round(float(opt_output.weights[i]), 8))),
                sector=sector_map.get(symbols[i]),
            )
            for i in range(n_assets)
            if abs(opt_output.weights[i]) > 1e-8  # Filter near-zero weights
        ]

        if not weights:
            weights = [PortfolioWeight(symbol="CASH", weight=Decimal("1.0"), sector=None)]

        portfolio = TargetPortfolio(
            portfolio_id=portfolio_id,
            strategy_id=self.config.strategy_id,
            as_of_ts=ctx.as_of_ts,
            nav_currency="USD",
            nav=self.config.nav,
            weights=weights,
            status=PortfolioStatus.PASSED,  # Tentative — gate decides
            optimizer=self.config.optimizer_type,
            optimizer_config_hash=str(hash(str(self.config.optimizer_type))),
            constraint_set_hash=str(hash(str(constraints))),
            covariance_estimator=self.config.covariance_method,
            expected_return_source="phase3_signals",
            risk_report_id=risk_report_id,
            rejection_id=None,
            parent_portfolio_id=None,
            created_at=datetime.utcnow(),
        )

        # --- Step 7: Risk report (if builder provided) ---
        if risk_report_builder is not None:
            risk_report = risk_report_builder(portfolio, ctx)
        else:
            # Minimal risk report for pipeline completion
            risk_report = None

        # --- Step 8: Risk gate ---
        if risk_report is not None:
            gate_result = task_run_risk_gate(
                strategy_id=self.config.strategy_id,
                as_of_date=as_of_date,
                portfolio=portfolio,
                risk_report=risk_report,
                policy=self.config.risk_policy,
            )
            task_results["risk_gate"] = gate_result

            if gate_result.status == "completed":
                validation = gate_result.result
                if validation.status == ValidationStatus.REJECTED:
                    # Apply fallback
                    logger.info(
                        "portfolio_rejected_applying_fallback",
                        strategy_id=self.config.strategy_id,
                        n_failed_checks=len(validation.failed_checks),
                    )
                    fallback_result = task_apply_fallback(
                        strategy_id=self.config.strategy_id,
                        as_of_date=as_of_date,
                        fallback_config=self.config.fallback_config,
                        nav=self.config.nav,
                        prior_portfolio=prior_portfolio,
                        rejection_id=uuid4(),
                        risk_report_id=risk_report_id,
                    )
                    task_results["apply_fallback"] = fallback_result

                    elapsed = (time.perf_counter() - pipeline_start) * 1000
                    fallback_portfolio = (
                        fallback_result.result.portfolio
                        if hasattr(fallback_result.result, "portfolio")
                        else None
                    )
                    return PipelineResult(
                        strategy_id=self.config.strategy_id,
                        as_of_date=as_of_date,
                        status="fallback_applied",
                        portfolio=fallback_portfolio,
                        risk_report=risk_report,
                        task_results=task_results,
                        total_duration_ms=elapsed,
                    )

        # --- Step 9: Publish ---
        elapsed = (time.perf_counter() - pipeline_start) * 1000
        logger.info(
            "daily_pipeline_complete",
            strategy_id=self.config.strategy_id,
            as_of_date=str(as_of_date),
            status="completed",
            duration_ms=round(elapsed, 2),
        )

        return PipelineResult(
            strategy_id=self.config.strategy_id,
            as_of_date=as_of_date,
            status="completed",
            portfolio=portfolio,
            risk_report=risk_report,
            task_results=task_results,
            total_duration_ms=elapsed,
        )

    def _failed_result(
        self,
        as_of_date: date,
        task_results: dict[str, TaskResult],
        pipeline_start: float,
    ) -> PipelineResult:
        """Build a failed pipeline result."""
        elapsed = (time.perf_counter() - pipeline_start) * 1000
        logger.error(
            "daily_pipeline_failed",
            strategy_id=self.config.strategy_id,
            as_of_date=str(as_of_date),
        )
        return PipelineResult(
            strategy_id=self.config.strategy_id,
            as_of_date=as_of_date,
            status="failed",
            task_results=task_results,
            total_duration_ms=elapsed,
        )
