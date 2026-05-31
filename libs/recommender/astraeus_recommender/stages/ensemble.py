"""Stage 4: Ensemble — regime-conditional signal combination and ranking.

Applies regime-conditional weights with correlation penalty and signal-decay tracking.
Outputs ranked candidates with per-signal attribution.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from ..contracts import (
    EnsembleCandidate,
    EnsembleOutput,
    RegimeDetection,
    SignalOutput,
)

if TYPE_CHECKING:
    from astraeus_ensemble import EnsembleEngine

logger = structlog.get_logger("astraeus.recommender.stages.ensemble")


class EnsembleStage:
    """Stage 4: Regime-conditional ensemble with ranking.

    Combines signal outputs using regime-specific weights, applies
    correlation penalties, and produces a ranked candidate list.
    """

    def __init__(
        self,
        engine: EnsembleEngine,
        top_n: int = 10,
    ) -> None:
        self._engine = engine
        self._top_n = top_n

    async def run(
        self,
        run_id: UUID,
        regime: RegimeDetection,
        signals: list[SignalOutput],
    ) -> EnsembleOutput:
        """Execute Stage 4: combine signals and rank candidates.

        Args:
            run_id: Pipeline run identifier.
            regime: Stage 2 output (current regime).
            signals: Stage 3 outputs (all signal generators).

        Returns:
            EnsembleOutput with ranked candidates and attribution.
        """
        start = time.perf_counter()

        logger.info(
            "stage4_ensemble_start",
            run_id=str(run_id),
            regime=regime.label,
            n_signals=len(signals),
        )

        # Get regime-conditional weights
        weights = await self._engine.get_weights(regime.label)

        # Build per-ticker composite scores
        ticker_scores: dict[str, dict[str, float]] = {}  # ticker -> {signal: weighted_score}

        for signal_output in signals:
            signal_name = signal_output.signal
            signal_weight = weights.get(signal_name, 0.0)

            if signal_weight == 0.0:
                continue

            for value in signal_output.values:
                if value.ticker not in ticker_scores:
                    ticker_scores[value.ticker] = {}

                # Use z-score if available, else raw score
                score = value.score_z if value.score_z is not None else value.score
                weighted = score * signal_weight * value.confidence
                ticker_scores[value.ticker][signal_name] = weighted

        # Compute composite scores with correlation penalty
        candidates: list[EnsembleCandidate] = []
        for ticker, attributions in ticker_scores.items():
            composite = sum(attributions.values())

            # Apply correlation penalty via the engine
            penalty = await self._engine.correlation_penalty(ticker, attributions)
            composite *= (1.0 - penalty)

            candidates.append(
                EnsembleCandidate(
                    ticker=ticker,
                    composite_score=composite,
                    rank=0,  # Will be set after sorting
                    component_attribution=attributions,
                )
            )

        # Sort by composite score descending, assign ranks
        candidates.sort(key=lambda c: c.composite_score, reverse=True)
        for i, candidate in enumerate(candidates):
            candidate.rank = i + 1

        # Take top-N
        top_candidates = candidates[: self._top_n]

        elapsed_ms = (time.perf_counter() - start) * 1000

        output = EnsembleOutput(
            run_id=run_id,
            regime=regime.label,
            candidates=top_candidates,
            weights_used=dict(weights.items()),
        )

        logger.info(
            "stage4_ensemble_complete",
            run_id=str(run_id),
            n_candidates=len(top_candidates),
            top_ticker=top_candidates[0].ticker if top_candidates else None,
            top_score=round(top_candidates[0].composite_score, 4) if top_candidates else None,
            elapsed_ms=round(elapsed_ms, 1),
        )

        return output
