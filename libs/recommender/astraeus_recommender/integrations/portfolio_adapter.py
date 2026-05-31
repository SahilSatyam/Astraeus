"""Adapter bridging Phase 7 ensemble output to Phase 4 optimizer interface.

Translates ensemble candidates into the OptContext format expected by
the Phase 4 optimizer ABC, and converts OptResult back to Phase 7 contracts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import numpy as np
import structlog

if TYPE_CHECKING:
    from astraeus_portfolio.optimizers.base import Optimizer

from ..contracts import EnsembleCandidate, PortfolioAllocation, PortfolioOutput, Side

logger = structlog.get_logger("astraeus.recommender.integrations.portfolio")


class PortfolioOptimizerAdapter:
    """Bridges Phase 7 ensemble output to Phase 4 optimizer.

    Constructs an OptContext from ensemble candidates and runs the
    Phase 4 optimizer, then converts the result back to Phase 7 format.
    """

    def __init__(
        self,
        optimizer: Optimizer,
        strategy_id: str = "recommender_v1",
        risk_aversion: float = 5.0,
        nav: float = 10000.0,
    ) -> None:
        self._optimizer = optimizer
        self._strategy_id = strategy_id
        self._risk_aversion = risk_aversion
        self._nav = nav

    async def optimize(
        self,
        candidates: list[EnsembleCandidate],
        covariance: np.ndarray | None = None,
        prices: np.ndarray | None = None,
        adv: np.ndarray | None = None,
        sector_map: dict[str, str] | None = None,
        beta: np.ndarray | None = None,
        regime_label: str | None = None,
    ) -> PortfolioOutput:
        """Run Phase 4 optimizer on ensemble candidates.

        Args:
            candidates: Ranked candidates from Stage 4.
            covariance: Covariance matrix (n x n). Uses identity if not provided.
            prices: Current prices per symbol.
            adv: 30-day ADV per symbol.
            sector_map: Symbol -> GICS sector mapping.
            beta: Rolling betas vs SPY.
            regime_label: Current regime for optimizer context.

        Returns:
            PortfolioOutput with sized allocations.
        """
        from astraeus_portfolio.contracts import OptContext

        n = len(candidates)
        symbols = [c.ticker for c in candidates]

        # Build expected returns from composite scores
        scores = np.array([c.composite_score for c in candidates])
        # Normalize to expected return scale (~annualized)
        max_score = np.max(np.abs(scores)) if np.any(scores != 0) else 1.0
        expected_returns = scores / max_score * 0.15  # Scale to ~15% max expected return

        # Default covariance: identity scaled by typical equity vol
        if covariance is None:
            covariance = np.eye(n) * (0.20**2 / 252)  # ~20% annualized vol

        # Default prices, ADV, beta
        if prices is None:
            prices = np.ones(n) * 100.0
        if adv is None:
            adv = np.ones(n) * 1_000_000
        if beta is None:
            beta = np.ones(n)
        if sector_map is None:
            sector_map = dict.fromkeys(symbols, "Unknown")

        ctx = OptContext(
            strategy_id=self._strategy_id,
            as_of_ts=datetime.now(tz=UTC),
            n_assets=n,
            symbols=symbols,
            expected_returns=expected_returns,
            covariance=covariance,
            current_weights=np.zeros(n),
            prices=prices,
            adv=adv,
            sector_map=sector_map,
            beta=beta,
            factor_loadings=None,
            views=None,
            scenarios=None,
            regime_label=regime_label,
            constraints=[],
            risk_aversion=self._risk_aversion,
            fully_invested=True,
            nav=Decimal(str(self._nav)),
            seed=42,
        )

        # Run the optimizer
        result = self._optimizer.run(ctx)

        # Convert to Phase 7 format
        allocations: list[PortfolioAllocation] = []
        if result.status in ("optimal", "optimal_inaccurate") and len(result.weights) == n:
            for symbol, weight in zip(symbols, result.weights.tolist(), strict=True):
                if abs(weight) < 1e-6:
                    continue
                side = Side.LONG if weight > 0 else Side.SHORT
                allocations.append(
                    PortfolioAllocation(ticker=symbol, side=side, target_weight=weight)
                )

        return PortfolioOutput(
            run_id=uuid4(),
            allocations=allocations,
            optimizer_used=result.solver_used or "unknown",
            solve_time_ms=result.solve_time_ms,
        )
