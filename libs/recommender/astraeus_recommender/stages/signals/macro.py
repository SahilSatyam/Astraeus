"""Macro signal generator.

Produces scores based on macroeconomic factor exposure:
interest rate sensitivity, sector rotation, cross-asset momentum.
"""

from __future__ import annotations

from ...contracts import DailyInputSnapshot, SignalName, SignalValue
from .base import SignalGenerator


class MacroSignal(SignalGenerator):
    """Macro-economic factor signal."""

    @property
    def name(self) -> SignalName:
        return SignalName.MACRO

    async def generate(self, snapshot: DailyInputSnapshot) -> list[SignalValue]:
        """Generate macro factor scores."""
        values: list[SignalValue] = []

        for symbol in snapshot.symbols:
            features = snapshot.feature_matrix.get(symbol, {})

            # Macro factor features
            rate_sensitivity = features.get("rate_sensitivity_beta")
            sector_momentum = features.get("sector_momentum_20d")
            dollar_beta = features.get("dollar_index_beta")
            credit_spread_beta = features.get("credit_spread_beta")
            yield_curve_signal = features.get("yield_curve_slope_signal")

            if all(
                v is None
                for v in [rate_sensitivity, sector_momentum, dollar_beta, credit_spread_beta]
            ):
                continue

            score = 0.0
            weight_sum = 0.0

            if sector_momentum is not None:
                # Sector rotation: favor sectors with positive momentum
                score += 0.35 * sector_momentum
                weight_sum += 0.35

            if rate_sensitivity is not None and yield_curve_signal is not None:
                # Rate-sensitive stocks benefit when rates are expected to fall
                rate_signal = -rate_sensitivity * yield_curve_signal
                score += 0.25 * rate_signal
                weight_sum += 0.25
            elif rate_sensitivity is not None:
                score += 0.15 * (-rate_sensitivity * 0.1)  # Mild bias against rate-sensitive
                weight_sum += 0.15

            if dollar_beta is not None:
                # Strong dollar hurts exporters (negative beta = benefits from weak dollar)
                score += 0.2 * (-dollar_beta * 0.5)
                weight_sum += 0.2

            if credit_spread_beta is not None:
                # Widening spreads hurt high-beta-to-credit names
                score += 0.2 * (-credit_spread_beta * 0.3)
                weight_sum += 0.2

            if weight_sum > 0:
                score /= weight_sum

            confidence = weight_sum / 1.0

            values.append(
                SignalValue(ticker=symbol, score=score, confidence=confidence)
            )

        return values
