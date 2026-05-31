"""Base class for signal generators.

Each signal generator is an independent service with its own state.
Per-signal SLA: < 5 min daily.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from uuid import UUID

import structlog

from ...contracts import DailyInputSnapshot, SignalName, SignalOutput, SignalValue

logger = structlog.get_logger("astraeus.recommender.stages.signals")


class SignalGenerator(ABC):
    """Abstract base for all signal generators.

    Subclasses implement `generate()` which produces raw scores.
    The base class handles timing, logging, and z-score normalization.
    """

    @property
    @abstractmethod
    def name(self) -> SignalName:
        """Canonical signal name."""

    @abstractmethod
    async def generate(
        self,
        snapshot: DailyInputSnapshot,
    ) -> list[SignalValue]:
        """Generate raw signal values for all symbols in the snapshot.

        Must NOT produce ranks — only raw scores and optional confidence.
        """

    async def run(
        self,
        run_id: UUID,
        snapshot: DailyInputSnapshot,
    ) -> SignalOutput:
        """Execute the signal generator with timing and z-score normalization."""
        start = time.perf_counter()

        logger.info("signal_start", signal=self.name, run_id=str(run_id))

        values = await self.generate(snapshot)

        # Compute cross-sectional z-scores
        values = self._compute_z_scores(values)

        elapsed_ms = (time.perf_counter() - start) * 1000

        output = SignalOutput(
            run_id=run_id,
            signal=self.name,
            values=values,
            compute_time_ms=elapsed_ms,
        )

        logger.info(
            "signal_complete",
            signal=self.name,
            run_id=str(run_id),
            n_values=len(values),
            elapsed_ms=round(elapsed_ms, 1),
        )

        return output

    @staticmethod
    def _compute_z_scores(values: list[SignalValue]) -> list[SignalValue]:
        """Compute cross-sectional z-scores for ranking normalization."""
        if not values:
            return values

        scores = [v.score for v in values]
        n = len(scores)
        if n < 2:
            return values

        mean = sum(scores) / n
        variance = sum((s - mean) ** 2 for s in scores) / (n - 1)
        std = variance**0.5

        if std < 1e-10:
            # All scores identical — z-scores are 0
            return [
                SignalValue(ticker=v.ticker, score=v.score, score_z=0.0, confidence=v.confidence)
                for v in values
            ]

        return [
            SignalValue(
                ticker=v.ticker,
                score=v.score,
                score_z=(v.score - mean) / std,
                confidence=v.confidence,
            )
            for v in values
        ]
