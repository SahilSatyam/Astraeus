"""Regime-conditional weight matrix.

Maintains a weight matrix of shape (n_regimes, n_signals) that determines
how much each signal contributes to the composite score under each regime.

Weights are learned from prior performance with shrinkage toward flat weights.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger("astraeus.ensemble.weights")


class WeightConfig(BaseModel):
    """Configuration for the weight matrix."""

    shrinkage_factor: float = Field(
        default=0.3, ge=0.0, le=1.0, description="Shrinkage toward equal weights"
    )
    min_weight: float = Field(default=0.0, description="Minimum signal weight")
    max_weight: float = Field(default=0.5, description="Maximum signal weight")


class RegimeWeightMatrix:
    """Regime-conditional signal weight matrix.

    Stores and retrieves weights per (regime, signal) pair.
    Applies shrinkage toward flat (equal) weights to prevent overfitting.
    """

    def __init__(
        self,
        signals: list[str],
        regimes: list[str],
        config: WeightConfig | None = None,
    ) -> None:
        self._signals = signals
        self._regimes = regimes
        self._config = config or WeightConfig()
        self._n_signals = len(signals)
        self._n_regimes = len(regimes)

        # Initialize with equal weights
        flat_weight = 1.0 / self._n_signals
        self._matrix: dict[str, dict[str, float]] = {
            regime: dict.fromkeys(signals, flat_weight)
            for regime in regimes
        }

    def get_weights(self, regime: str) -> dict[str, float]:
        """Get signal weights for a given regime.

        Falls back to flat weights if regime is unknown.
        """
        if regime in self._matrix:
            return dict(self._matrix[regime])

        # Unknown regime: return flat weights
        flat = 1.0 / self._n_signals
        return dict.fromkeys(self._signals, flat)

    def update_weights(
        self,
        regime: str,
        signal_performance: dict[str, float],
    ) -> None:
        """Update weights based on signal performance.

        Applies shrinkage toward flat weights to prevent overfitting.

        Args:
            regime: The regime these weights apply to.
            signal_performance: signal_name -> performance metric (e.g., Sharpe).
        """
        if regime not in self._matrix:
            logger.warning("unknown_regime_for_update", regime=regime)
            return

        # Compute raw weights proportional to performance
        performances = []
        for signal in self._signals:
            perf = signal_performance.get(signal, 0.0)
            performances.append(max(perf, 0.0))  # Floor at 0

        total = sum(performances)
        if total < 1e-10:
            # All signals performed poorly — keep flat
            return

        raw_weights = [p / total for p in performances]

        # Apply shrinkage toward flat weights
        flat = 1.0 / self._n_signals
        shrinkage = self._config.shrinkage_factor
        shrunk_weights = [
            shrinkage * flat + (1.0 - shrinkage) * w for w in raw_weights
        ]

        # Clip to bounds
        clipped = [
            max(self._config.min_weight, min(self._config.max_weight, w))
            for w in shrunk_weights
        ]

        # Renormalize
        total_clipped = sum(clipped)
        if total_clipped > 0:
            normalized = [w / total_clipped for w in clipped]
        else:
            normalized = [flat] * self._n_signals

        # Store
        for signal, weight in zip(self._signals, normalized, strict=True):
            self._matrix[regime][signal] = weight

        logger.info(
            "weights_updated",
            regime=regime,
            weights={s: round(w, 4) for s, w in zip(self._signals, normalized, strict=True)},
        )

    @property
    def matrix(self) -> dict[str, dict[str, float]]:
        """Full weight matrix (regime -> signal -> weight)."""
        return {r: dict(w) for r, w in self._matrix.items()}
