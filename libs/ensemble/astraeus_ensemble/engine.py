"""Ensemble engine — combines weights, correlation penalty, and decay.

This is the main interface consumed by Stage 4 of the recommendation pipeline.
"""

from __future__ import annotations

import structlog

from .correlation_penalty import CorrelationPenalty
from .decay import DecayTracker
from .weights import RegimeWeightMatrix, WeightConfig

logger = structlog.get_logger("astraeus.ensemble.engine")

# Default signal and regime lists
DEFAULT_SIGNALS = ["technical", "statistical", "ml_xgb", "nlp_sentiment", "macro"]
DEFAULT_REGIMES = [
    "risk_on",
    "risk_off",
    "vol_spike",
    "mean_reversion",
    "trending",
    "uncertain",
]


class EnsembleEngine:
    """Regime-conditional ensemble engine.

    Combines:
    - Regime-conditional weight matrix
    - Correlation penalty (prevents double-counting)
    - Signal decay tracking (down-weights failing signals)

    Usage:
        engine = EnsembleEngine()
        weights = await engine.get_weights("risk_on")
        penalty = await engine.correlation_penalty("AAPL", attributions)
    """

    def __init__(
        self,
        signals: list[str] | None = None,
        regimes: list[str] | None = None,
        weight_config: WeightConfig | None = None,
        correlation_threshold: float = 0.7,
        max_correlation_penalty: float = 0.3,
    ) -> None:
        signals = signals or DEFAULT_SIGNALS
        regimes = regimes or DEFAULT_REGIMES

        self._weight_matrix = RegimeWeightMatrix(
            signals=signals,
            regimes=regimes,
            config=weight_config,
        )
        self._correlation = CorrelationPenalty(
            penalty_threshold=correlation_threshold,
            max_penalty=max_correlation_penalty,
        )
        self._decay = DecayTracker()
        self._signals = signals

    async def get_weights(self, regime: str) -> dict[str, float]:
        """Get regime-conditional weights with decay applied.

        Args:
            regime: Current market regime label.

        Returns:
            Dict of signal_name -> effective weight (after decay).
        """
        raw_weights = self._weight_matrix.get_weights(regime)

        # Apply decay factors
        effective: dict[str, float] = {}
        for signal, weight in raw_weights.items():
            decay = self._decay.get_decay_factor(signal)
            effective[signal] = weight * decay

        # Renormalize
        total = sum(effective.values())
        if total > 1e-10:
            effective = {s: w / total for s, w in effective.items()}

        return effective

    async def correlation_penalty(self, ticker: str, attributions: dict[str, float]) -> float:
        """Compute correlation penalty for a ticker's signal attributions.

        Args:
            ticker: The ticker symbol.
            attributions: signal_name -> weighted contribution.

        Returns:
            Penalty factor in [0, max_penalty].
        """
        return self._correlation.compute_penalty(attributions)

    def update_signal_correlations(self, signal_scores: dict[str, dict[str, float]]) -> None:
        """Update inter-signal correlation estimates.

        Args:
            signal_scores: signal_name -> {ticker: score} from recent period.
        """
        self._correlation.update_correlations(signal_scores)

    def update_weights(self, regime: str, signal_performance: dict[str, float]) -> None:
        """Update regime-conditional weights from performance data.

        Args:
            regime: Regime label.
            signal_performance: signal_name -> performance metric.
        """
        self._weight_matrix.update_weights(regime, signal_performance)

    @property
    def decay_tracker(self) -> DecayTracker:
        """Access the decay tracker for recording performance."""
        return self._decay

    @property
    def weight_matrix(self) -> RegimeWeightMatrix:
        """Access the weight matrix for inspection."""
        return self._weight_matrix
