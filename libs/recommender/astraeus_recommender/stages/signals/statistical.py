"""Statistical signal generator.

Produces scores from statistical arbitrage features:
z-score of price vs moving average, Hurst exponent, cointegration residuals.
"""

from __future__ import annotations

from ...contracts import DailyInputSnapshot, SignalName, SignalValue
from .base import SignalGenerator


class StatisticalSignal(SignalGenerator):
    """Statistical arbitrage signal: mean-reversion + regime persistence."""

    @property
    def name(self) -> SignalName:
        return SignalName.STATISTICAL

    async def generate(self, snapshot: DailyInputSnapshot) -> list[SignalValue]:
        """Generate statistical scores from mean-reversion features."""
        values: list[SignalValue] = []

        for symbol in snapshot.symbols:
            features = snapshot.feature_matrix.get(symbol, {})

            # Z-score of price relative to moving averages
            zscore_20 = features.get("price_zscore_20d")
            zscore_60 = features.get("price_zscore_60d")
            hurst = features.get("hurst_exponent")
            half_life = features.get("mean_reversion_half_life")

            if zscore_20 is None and zscore_60 is None:
                continue

            score = 0.0
            weight_sum = 0.0

            if zscore_20 is not None:
                # Mean-reversion: negative z-score → expect reversion up
                score += 0.35 * (-zscore_20)
                weight_sum += 0.35

            if zscore_60 is not None:
                score += 0.25 * (-zscore_60)
                weight_sum += 0.25

            if hurst is not None:
                # Hurst < 0.5 → mean-reverting, > 0.5 → trending
                # For stat-arb, we want mean-reverting assets
                hurst_signal = (0.5 - hurst) * 2.0  # Normalized
                score += 0.25 * hurst_signal
                weight_sum += 0.25

            if half_life is not None:
                # Shorter half-life → stronger mean-reversion → higher score
                # Normalize: half_life of 5 days → score 1.0, 60 days → score 0.0
                hl_signal = max(0.0, min(1.0, (60.0 - half_life) / 55.0))
                score += 0.15 * hl_signal
                weight_sum += 0.15

            if weight_sum > 0:
                score /= weight_sum

            confidence = weight_sum / 1.0

            values.append(SignalValue(ticker=symbol, score=score, confidence=confidence))

        return values
