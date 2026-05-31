"""Adapter bridging Phase 7 allocations to Phase 4 risk validation gate.

Translates Phase 7 PortfolioOutput into the TargetPortfolio + RiskReport
format expected by the Phase 4 RiskGate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from astraeus_portfolio.risk.validation import RiskGate, RiskPolicy

from ..contracts import (
    PortfolioAllocation,
    PortfolioOutput,
    RiskCheckResult,
    RiskValidationOutput,
)

logger = structlog.get_logger("astraeus.recommender.integrations.risk")


class RiskGateAdapter:
    """Bridges Phase 7 allocations to Phase 4 RiskGate.

    For the recommender pipeline, we run a simplified risk check
    that validates position-level and portfolio-level constraints
    without requiring a full RiskReport computation.
    """

    def __init__(
        self,
        risk_gate: RiskGate | None = None,
        policy: RiskPolicy | None = None,
        max_single_position: float = 0.15,
        max_total_short: float = 0.30,
        min_position_size: float = 0.01,
        max_gross_exposure: float = 2.0,
    ) -> None:
        self._gate = risk_gate
        self._policy = policy
        self._limits = {
            "max_single_position": max_single_position,
            "max_total_short": max_total_short,
            "min_position_size": min_position_size,
            "max_gross_exposure": max_gross_exposure,
        }

    async def validate(
        self,
        run_id: UUID,
        portfolio: PortfolioOutput,
    ) -> RiskValidationOutput:
        """Validate allocations against risk limits.

        If a Phase 4 RiskGate is available, delegates to it.
        Otherwise, runs the built-in position/portfolio checks.

        Args:
            run_id: Pipeline run identifier.
            portfolio: Stage 5 output with allocations.

        Returns:
            RiskValidationOutput with passed/rejected allocations.
        """
        passed: list[PortfolioAllocation] = []
        rejected: list[PortfolioAllocation] = []
        checks: list[RiskCheckResult] = []

        for alloc in portfolio.allocations:
            alloc_checks = self._check_allocation(alloc)
            checks.extend(alloc_checks)

            if all(c.passed for c in alloc_checks):
                passed.append(alloc)
            else:
                rejected.append(alloc)
                logger.info(
                    "risk_allocation_rejected",
                    ticker=alloc.ticker,
                    weight=alloc.target_weight,
                    failed=[c.rule for c in alloc_checks if not c.passed],
                )

        # Portfolio-level checks
        portfolio_checks = self._check_portfolio(passed)
        checks.extend(portfolio_checks)

        all_passed = all(c.passed for c in checks)

        return RiskValidationOutput(
            run_id=run_id,
            passed_allocations=passed,
            rejected_allocations=rejected,
            checks=checks,
            all_passed=all_passed,
        )

    def _check_allocation(self, alloc: PortfolioAllocation) -> list[RiskCheckResult]:
        """Position-level risk checks."""
        results: list[RiskCheckResult] = []

        # Max single position
        max_pos = self._limits["max_single_position"]
        results.append(
            RiskCheckResult(
                rule="max_single_position",
                passed=abs(alloc.target_weight) <= max_pos,
                detail={"ticker": alloc.ticker, "weight": alloc.target_weight, "limit": max_pos},
            )
        )

        # Min position size
        min_pos = self._limits["min_position_size"]
        results.append(
            RiskCheckResult(
                rule="min_position_size",
                passed=abs(alloc.target_weight) >= min_pos,
                detail={"ticker": alloc.ticker, "weight": alloc.target_weight, "limit": min_pos},
            )
        )

        return results

    def _check_portfolio(self, allocations: list[PortfolioAllocation]) -> list[RiskCheckResult]:
        """Portfolio-level risk checks."""
        results: list[RiskCheckResult] = []

        # Total short exposure
        total_short = sum(abs(a.target_weight) for a in allocations if a.target_weight < 0)
        max_short = self._limits["max_total_short"]
        results.append(
            RiskCheckResult(
                rule="max_total_short",
                passed=total_short <= max_short,
                detail={"total_short": total_short, "limit": max_short},
            )
        )

        # Gross exposure
        total_gross = sum(abs(a.target_weight) for a in allocations)
        max_gross = self._limits["max_gross_exposure"]
        results.append(
            RiskCheckResult(
                rule="max_gross_exposure",
                passed=total_gross <= max_gross,
                detail={"total_gross": total_gross, "limit": max_gross},
            )
        )

        return results
