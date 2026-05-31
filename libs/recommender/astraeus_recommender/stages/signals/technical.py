"""Technical signal generator.

Produces momentum, mean-reversion, and trend-following scores
from price/volume features in the snapshot.
"""

from __future__ import annotations

from ...contracts import DailyInputSnapshot, SignalName, SignalValue
from .base import SignalGenerator


class TechnicalSignal(SignalGenerator):
    """Technical analysis signal: momentum + trend composite."""

    @property
    def name(self) -> SignalName:
        return SignalName.TECHNICAL

    async def generate(self, snapshot: DailyInputSnapshot) -> list[SignalValue]:
        """Generate technical scores from price/volume features."""
        values: list[SignalValue] = []

        for symbol in snapshot.symbols:
            features = snapshot.feature_matrix.get(symbol, {})

            # Composite of momentum features
            mom_20 = features.get("momentum_20d")
            mom_60 = features.get("momentum_60d")
            rsi_14 = features.get("rsi_14d")
            vol_ratio = features.get("volume_ratio_20d")

            if mom_20 is None and mom_60 is None:
                continue

            # Weighted composite: short-term momentum + longer-term + mean-reversion from RSI
            score = 0.0
            weight_sum = 0.0

            if mom_20 is not None:
                score += 0.4 * mom_20
                weight_sum += 0.4

            if mom_60 is not None:
                score += 0.3 * mom_60
                weight_sum += 0.3

            if rsi_14 is not None:
                # RSI mean-reversion: oversold (< 30) is bullish, overbought (> 70) bearish
                rsi_signal = (50.0 - rsi_14) / 50.0  # Normalized to [-1, 1]
                score += 0.2 * rsi_signal
                weight_sum += 0.2

            if vol_ratio is not None:
                # Volume confirmation: above-average volume confirms direction
                vol_signal = min(max(vol_ratio - 1.0, -1.0), 1.0)
                score += 0.1 * vol_signal
                weight_sum += 0.1

            if weight_sum > 0:
                score /= weight_sum

            # Confidence based on data completeness
            confidence = weight_sum / 1.0  # max possible weight_sum is 1.0

            values.append(
                SignalValue(ticker=symbol, score=score, confidence=confidence)
            )

        return values
