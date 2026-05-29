"""Constraint relaxation fallback strategy.

Defines the FallbackPolicy that determines what happens when a portfolio
fails risk validation or when the optimizer cannot find a feasible solution.

Fallback actions (per strategy config):
- cash: target portfolio = 100% cash position.
- hold_prior: target portfolio = previous day's accepted portfolio.
- retry_relaxed: re-run optimization with relaxed constraints (once only).
- escalate_hitl: pin in human review queue; no portfolio published.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import structlog

from astraeus_portfolio.contracts import (
    FallbackAction,
    OptResult,
    PortfolioStatus,
    PortfolioWeight,
    TargetPortfolio,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class FallbackConfig:
    """Per-strategy fallback configuration.

    Attributes:
        action: The fallback action to take on rejection.
        max_retry_attempts: Maximum retry attempts for retry_relaxed (always 1).
        relaxation_drop_count: Number of constraints to pre-drop on retry.
    """

    action: FallbackAction = FallbackAction.HOLD_PRIOR
    max_retry_attempts: int = 1
    relaxation_drop_count: int = 1


@dataclass
class FallbackOutcome:
    """Result of applying a fallback policy.

    Attributes:
        action_taken: The fallback action that was executed.
        portfolio: The resulting portfolio (None if escalated to HITL).
        details: Additional context about the fallback execution.
    """

    action_taken: FallbackAction
    portfolio: TargetPortfolio | None
    details: dict[str, Any] = field(default_factory=dict)


class FallbackExecutor:
    """Executes fallback policies when portfolios are rejected or infeasible.

    The executor is stateless — it receives all necessary context as arguments
    and returns a FallbackOutcome describing what was done.
    """

    def execute(
        self,
        config: FallbackConfig,
        strategy_id: str,
        as_of_ts: datetime,
        nav: Decimal,
        prior_portfolio: TargetPortfolio | None,
        optimizer_run: Any | None = None,
        risk_report_id: UUID | None = None,
        rejection_id: UUID | None = None,
    ) -> FallbackOutcome:
        """Apply the configured fallback action.

        Args:
            config: The fallback configuration for this strategy.
            strategy_id: Strategy identifier.
            as_of_ts: Point-in-time timestamp.
            nav: Current NAV.
            prior_portfolio: Previous day's accepted portfolio (for hold_prior).
            optimizer_run: Callable to re-run optimization (for retry_relaxed).
            risk_report_id: UUID of the risk report that triggered rejection.
            rejection_id: UUID of the rejection record.

        Returns:
            FallbackOutcome describing the action taken and resulting portfolio.
        """
        action = config.action

        if action == FallbackAction.CASH:
            return self._apply_cash(
                strategy_id=strategy_id,
                as_of_ts=as_of_ts,
                nav=nav,
                risk_report_id=risk_report_id,
                rejection_id=rejection_id,
            )
        if action == FallbackAction.HOLD_PRIOR:
            return self._apply_hold_prior(
                strategy_id=strategy_id,
                as_of_ts=as_of_ts,
                nav=nav,
                prior_portfolio=prior_portfolio,
                risk_report_id=risk_report_id,
                rejection_id=rejection_id,
            )
        if action == FallbackAction.RETRY_RELAXED:
            return self._apply_retry_relaxed(
                config=config,
                strategy_id=strategy_id,
                as_of_ts=as_of_ts,
                nav=nav,
                optimizer_run=optimizer_run,
                risk_report_id=risk_report_id,
                rejection_id=rejection_id,
            )
        if action == FallbackAction.ESCALATE_HITL:
            return self._apply_escalate(
                strategy_id=strategy_id,
                rejection_id=rejection_id,
            )
        logger.error("unknown_fallback_action", action=action)
        return FallbackOutcome(
            action_taken=action,
            portfolio=None,
            details={"error": f"Unknown fallback action: {action}"},
        )

    def _apply_cash(
        self,
        strategy_id: str,
        as_of_ts: datetime,
        nav: Decimal,
        risk_report_id: UUID | None,
        rejection_id: UUID | None,
    ) -> FallbackOutcome:
        """Fallback to 100% cash position."""
        logger.info("fallback_cash", strategy_id=strategy_id)

        portfolio = TargetPortfolio(
            portfolio_id=uuid4(),
            strategy_id=strategy_id,
            as_of_ts=as_of_ts,
            nav_currency="USD",
            nav=nav,
            weights=[PortfolioWeight(symbol="CASH", weight=Decimal("1.0"), sector=None)],
            status=PortfolioStatus.FALLBACK_APPLIED,
            optimizer="mvo",  # placeholder — no optimizer was used
            optimizer_config_hash="fallback_cash",
            constraint_set_hash="fallback_cash",
            covariance_estimator="ledoit_wolf",
            expected_return_source="fallback",
            risk_report_id=risk_report_id or uuid4(),
            rejection_id=rejection_id,
            parent_portfolio_id=None,
            created_at=datetime.utcnow(),
        )

        return FallbackOutcome(
            action_taken=FallbackAction.CASH,
            portfolio=portfolio,
            details={"reason": "Risk validation failed; moved to cash."},
        )

    def _apply_hold_prior(
        self,
        strategy_id: str,
        as_of_ts: datetime,
        nav: Decimal,
        prior_portfolio: TargetPortfolio | None,
        risk_report_id: UUID | None,
        rejection_id: UUID | None,
    ) -> FallbackOutcome:
        """Hold the previous day's accepted portfolio."""
        if prior_portfolio is None:
            logger.warning(
                "fallback_hold_prior_no_prior_available",
                strategy_id=strategy_id,
            )
            # No prior portfolio — fall back to cash
            return self._apply_cash(
                strategy_id=strategy_id,
                as_of_ts=as_of_ts,
                nav=nav,
                risk_report_id=risk_report_id,
                rejection_id=rejection_id,
            )

        logger.info(
            "fallback_hold_prior",
            strategy_id=strategy_id,
            parent_portfolio_id=str(prior_portfolio.portfolio_id),
        )

        portfolio = TargetPortfolio(
            portfolio_id=uuid4(),
            strategy_id=strategy_id,
            as_of_ts=as_of_ts,
            nav_currency=prior_portfolio.nav_currency,
            nav=nav,
            weights=prior_portfolio.weights,
            status=PortfolioStatus.FALLBACK_APPLIED,
            optimizer=prior_portfolio.optimizer,
            optimizer_config_hash=prior_portfolio.optimizer_config_hash,
            constraint_set_hash=prior_portfolio.constraint_set_hash,
            covariance_estimator=prior_portfolio.covariance_estimator,
            expected_return_source=prior_portfolio.expected_return_source,
            risk_report_id=risk_report_id or uuid4(),
            rejection_id=rejection_id,
            parent_portfolio_id=prior_portfolio.portfolio_id,
            created_at=datetime.utcnow(),
        )

        return FallbackOutcome(
            action_taken=FallbackAction.HOLD_PRIOR,
            portfolio=portfolio,
            details={
                "reason": "Risk validation failed; holding prior portfolio.",
                "parent_portfolio_id": str(prior_portfolio.portfolio_id),
            },
        )

    def _apply_retry_relaxed(
        self,
        config: FallbackConfig,
        strategy_id: str,
        as_of_ts: datetime,
        nav: Decimal,
        optimizer_run: Any | None,
        risk_report_id: UUID | None,
        rejection_id: UUID | None,
    ) -> FallbackOutcome:
        """Re-run optimization with relaxed constraints (once only).

        If optimizer_run is not provided or the retry also fails,
        falls back to hold_prior behavior (which itself may fall to cash).
        """
        if optimizer_run is None:
            logger.warning(
                "fallback_retry_no_optimizer_callable",
                strategy_id=strategy_id,
            )
            return FallbackOutcome(
                action_taken=FallbackAction.RETRY_RELAXED,
                portfolio=None,
                details={"error": "No optimizer callable provided for retry."},
            )

        logger.info(
            "fallback_retry_relaxed",
            strategy_id=strategy_id,
            max_attempts=config.max_retry_attempts,
        )

        try:
            result: OptResult = optimizer_run()
            if result.status in ("optimal", "optimal_inaccurate"):
                return FallbackOutcome(
                    action_taken=FallbackAction.RETRY_RELAXED,
                    portfolio=None,  # Caller builds TargetPortfolio from OptResult
                    details={
                        "reason": "Retry with relaxed constraints succeeded.",
                        "opt_result_status": result.status,
                        "relaxation_events": [e.model_dump() for e in result.relaxation_events],
                    },
                )
            logger.warning(
                "fallback_retry_still_infeasible",
                strategy_id=strategy_id,
                status=result.status,
            )
            return FallbackOutcome(
                action_taken=FallbackAction.RETRY_RELAXED,
                portfolio=None,
                details={
                    "error": "Retry with relaxed constraints still infeasible.",
                    "opt_result_status": result.status,
                },
            )
        except Exception as exc:
            logger.error(
                "fallback_retry_exception",
                strategy_id=strategy_id,
                error=str(exc),
                exc_info=True,
            )
            return FallbackOutcome(
                action_taken=FallbackAction.RETRY_RELAXED,
                portfolio=None,
                details={"error": f"Retry raised exception: {exc}"},
            )

    def _apply_escalate(
        self,
        strategy_id: str,
        rejection_id: UUID | None,
    ) -> FallbackOutcome:
        """Escalate to human-in-the-loop review. No portfolio published."""
        logger.info(
            "fallback_escalate_hitl",
            strategy_id=strategy_id,
            rejection_id=str(rejection_id) if rejection_id else None,
        )

        return FallbackOutcome(
            action_taken=FallbackAction.ESCALATE_HITL,
            portfolio=None,
            details={
                "reason": "Escalated to human review. No portfolio published.",
                "rejection_id": str(rejection_id) if rejection_id else None,
            },
        )
