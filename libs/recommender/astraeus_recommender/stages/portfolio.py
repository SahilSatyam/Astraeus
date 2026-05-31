"""Stage 5: Portfolio Construction — thin wrapper on Phase 4 optimizers.

Converts ensemble candidates into sized positions using the portfolio
construction engine from Phase 4.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import structlog

from ..contracts import (
    EnsembleOutput,
    PortfolioAllocation,
    PortfolioOutput,
    Side,
)

logger = structlog.get_logger("astraeus.recommender.stages.portfolio")


class PortfolioStage:
    """Stage 5: Position sizing via Phase 4 optimizers.

    Takes ranked candidates from the ensemble and produces target weights
    using the existing portfolio construction infrastructure.
    """

    def __init__(self, optimizer: Any) -> None:
        """Initialize with a Phase 4 optimizer instance.

        Args:
            optimizer: An optimizer from astraeus_portfolio.optimizers that
                      implements the OptContext -> OptResult interface.
        """
        self._optimizer = optimizer

    async def run(
        self,
        run_id: UUID,
        ensemble: EnsembleOutput,
    ) -> PortfolioOutput:
        """Execute Stage 5: size positions for ensemble candidates.

        Args:
            run_id: Pipeline run identifier.
            ensemble: Stage 4 output with ranked candidates.

        Returns:
            PortfolioOutput with sized allocations.
        """
        start = time.perf_counter()

        logger.info(
            "stage5_portfolio_start",
            run_id=str(run_id),
            n_candidates=len(ensemble.candidates),
        )

        allocations: list[PortfolioAllocation] = []

        if not ensemble.candidates:
            logger.warning("stage5_no_candidates", run_id=str(run_id))
            return PortfolioOutput(
                run_id=run_id,
                allocations=[],
                optimizer_used="none",
                solve_time_ms=0.0,
            )

        # Convert ensemble scores to expected returns for the optimizer
        # Higher composite score → higher expected return
        symbols = [c.ticker for c in ensemble.candidates]
        scores = [c.composite_score for c in ensemble.candidates]

        # Normalize scores to expected return scale
        max_score = max(abs(s) for s in scores) if scores else 1.0
        expected_returns = [s / max_score * 0.1 for s in scores]  # Scale to ~10% max

        # Run optimizer (simplified interface for the recommender)
        try:
            result = await self._run_optimizer(symbols, expected_returns)
            optimizer_used = result.get("optimizer", "equal_weight")
            weights = result.get("weights", {})
            solve_time = result.get("solve_time_ms", 0.0)
        except Exception as e:
            logger.warning(
                "stage5_optimizer_fallback",
                run_id=str(run_id),
                error=str(e),
            )
            # Fallback: equal-weight the top candidates
            n = len(symbols)
            weights = dict.fromkeys(symbols, 1.0 / n)
            optimizer_used = "equal_weight_fallback"
            solve_time = 0.0

        # Build allocations
        for symbol in symbols:
            weight = weights.get(symbol, 0.0)
            if abs(weight) < 1e-6:
                continue

            side = Side.LONG if weight > 0 else Side.SHORT
            allocations.append(PortfolioAllocation(ticker=symbol, side=side, target_weight=weight))

        elapsed_ms = (time.perf_counter() - start) * 1000

        output = PortfolioOutput(
            run_id=run_id,
            allocations=allocations,
            optimizer_used=optimizer_used,
            solve_time_ms=solve_time,
        )

        logger.info(
            "stage5_portfolio_complete",
            run_id=str(run_id),
            n_allocations=len(allocations),
            optimizer=optimizer_used,
            elapsed_ms=round(elapsed_ms, 1),
        )

        return output

    async def _run_optimizer(
        self, symbols: list[str], expected_returns: list[float]
    ) -> dict[str, Any]:
        """Run the Phase 4 optimizer.

        This is the integration point with astraeus_portfolio.
        Returns a dict with 'optimizer', 'weights', 'solve_time_ms'.
        """
        import numpy as np

        # If we have a real optimizer, use it
        if self._optimizer is not None and hasattr(self._optimizer, "optimize"):
            result = await self._optimizer.optimize(
                symbols=symbols,
                expected_returns=np.array(expected_returns),
            )
            return {
                "optimizer": getattr(result, "solver_used", "unknown"),
                "weights": dict(zip(symbols, result.weights.tolist(), strict=True)),
                "solve_time_ms": getattr(result, "solve_time_ms", 0.0),
            }

        # Fallback: score-proportional weighting
        total = sum(abs(r) for r in expected_returns)
        if total < 1e-10:
            weights = {s: 1.0 / len(symbols) for s in symbols}
        else:
            weights = {s: r / total for s, r in zip(symbols, expected_returns, strict=True)}

        return {"optimizer": "score_proportional", "weights": weights, "solve_time_ms": 0.0}
