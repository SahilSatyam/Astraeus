"""Stage 6: Risk Validation Gate — thin wrapper on Phase 4 risk engine.

Validates each allocation against risk limits. Rejected allocations are logged
but do not fail the run — they're excluded from recommendations.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import structlog

from ..contracts import (
    PortfolioAllocation,
    PortfolioOutput,
    RiskCheckResult,
    RiskValidationOutput,
)

logger = structlog.get_logger("astraeus.recommender.stages.risk")


# Default risk limits for the recommendation engine
DEFAULT_RISK_LIMITS = {
    "max_single_position": 0.15,  # 15% max per position
    "max_sector_concentration": 0.40,  # 40% max per sector
    "max_total_short": 0.30,  # 30% max short exposure
    "min_position_size": 0.01,  # 1% minimum to be actionable
    "max_portfolio_beta": 1.5,  # Max portfolio beta
}


class RiskStage:
    """Stage 6: Risk validation gate.

    Applies position-level and portfolio-level risk checks.
    Rejected positions are logged with reasons but don't fail the pipeline.
    """

    def __init__(
        self,
        risk_engine: Any = None,
        limits: dict[str, float] | None = None,
    ) -> None:
        """Initialize with Phase 4 risk engine and limits.

        Args:
            risk_engine: Phase 4 risk validation engine (optional).
            limits: Risk limit overrides.
        """
        self._engine = risk_engine
        self._limits = limits or DEFAULT_RISK_LIMITS

    async def run(
        self,
        run_id: UUID,
        portfolio: PortfolioOutput,
    ) -> RiskValidationOutput:
        """Execute Stage 6: validate allocations against risk limits.

        Args:
            run_id: Pipeline run identifier.
            portfolio: Stage 5 output with sized allocations.

        Returns:
            RiskValidationOutput with passed/rejected allocations and check details.
        """
        start = time.perf_counter()

        logger.info(
            "stage6_risk_start",
            run_id=str(run_id),
            n_allocations=len(portfolio.allocations),
        )

        passed: list[PortfolioAllocation] = []
        rejected: list[PortfolioAllocation] = []
        checks: list[RiskCheckResult] = []

        for alloc in portfolio.allocations:
            alloc_checks = self._validate_allocation(alloc)
            checks.extend(alloc_checks)

            if all(c.passed for c in alloc_checks):
                passed.append(alloc)
            else:
                rejected.append(alloc)
                failed_rules = [c.rule for c in alloc_checks if not c.passed]
                logger.warning(
                    "stage6_allocation_rejected",
                    run_id=str(run_id),
                    ticker=alloc.ticker,
                    failed_rules=failed_rules,
                )

        # Portfolio-level checks
        portfolio_checks = self._validate_portfolio(passed)
        checks.extend(portfolio_checks)

        all_passed = all(c.passed for c in checks)

        elapsed_ms = (time.perf_counter() - start) * 1000

        output = RiskValidationOutput(
            run_id=run_id,
            passed_allocations=passed,
            rejected_allocations=rejected,
            checks=checks,
            all_passed=all_passed,
        )

        logger.info(
            "stage6_risk_complete",
            run_id=str(run_id),
            passed=len(passed),
            rejected=len(rejected),
            all_passed=all_passed,
            elapsed_ms=round(elapsed_ms, 1),
        )

        return output

    def _validate_allocation(self, alloc: PortfolioAllocation) -> list[RiskCheckResult]:
        """Run position-level risk checks on a single allocation."""
        results: list[RiskCheckResult] = []

        # Check: max single position size
        max_pos = self._limits["max_single_position"]
        results.append(
            RiskCheckResult(
                rule="max_single_position",
                passed=abs(alloc.target_weight) <= max_pos,
                detail={
                    "ticker": alloc.ticker,
                    "weight": alloc.target_weight,
                    "limit": max_pos,
                },
            )
        )

        # Check: minimum position size (too small to be actionable)
        min_pos = self._limits["min_position_size"]
        results.append(
            RiskCheckResult(
                rule="min_position_size",
                passed=abs(alloc.target_weight) >= min_pos,
                detail={
                    "ticker": alloc.ticker,
                    "weight": alloc.target_weight,
                    "limit": min_pos,
                },
            )
        )

        return results

    def _validate_portfolio(self, allocations: list[PortfolioAllocation]) -> list[RiskCheckResult]:
        """Run portfolio-level risk checks."""
        results: list[RiskCheckResult] = []

        # Check: total short exposure
        total_short = sum(abs(a.target_weight) for a in allocations if a.target_weight < 0)
        max_short = self._limits["max_total_short"]
        results.append(
            RiskCheckResult(
                rule="max_total_short",
                passed=total_short <= max_short,
                detail={"total_short": total_short, "limit": max_short},
            )
        )

        # Check: total gross exposure (sanity)
        total_gross = sum(abs(a.target_weight) for a in allocations)
        results.append(
            RiskCheckResult(
                rule="gross_exposure_sanity",
                passed=total_gross <= 2.0,  # Max 200% gross
                detail={"total_gross": total_gross, "limit": 2.0},
            )
        )

        return results
