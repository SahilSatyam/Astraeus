"""ML (XGBoost) signal generator.

Produces forward-return predictions from a pre-trained XGBoost model.
The model is loaded from the strategy registry (Phase 3).
"""

from __future__ import annotations

from typing import Any

from ...contracts import DailyInputSnapshot, SignalName, SignalValue
from .base import SignalGenerator


class MLXGBSignal(SignalGenerator):
    """Machine learning signal using XGBoost predictions."""

    def __init__(self, model: Any = None, feature_columns: list[str] | None = None) -> None:
        """Initialize with a pre-trained model.

        Args:
            model: Pre-trained XGBoost model (or compatible predict interface).
            feature_columns: Ordered list of feature names the model expects.
        """
        self._model = model
        self._feature_columns = feature_columns or []

    @property
    def name(self) -> SignalName:
        return SignalName.ML_XGB

    async def generate(self, snapshot: DailyInputSnapshot) -> list[SignalValue]:
        """Generate ML predictions for all symbols."""
        values: list[SignalValue] = []

        if self._model is None:
            # No model loaded — return empty (graceful degradation)
            return values

        for symbol in snapshot.symbols:
            features = snapshot.feature_matrix.get(symbol, {})

            # Build feature vector in the order the model expects
            feature_vec = []
            missing_count = 0
            for col in self._feature_columns:
                val = features.get(col)
                if val is None:
                    feature_vec.append(0.0)  # Impute missing with 0
                    missing_count += 1
                else:
                    feature_vec.append(val)

            # Skip if too many features are missing
            if missing_count > len(self._feature_columns) * 0.5:
                continue

            # Predict
            try:
                import numpy as np

                X = np.array([feature_vec])
                prediction = float(self._model.predict(X)[0])
            except Exception:  # noqa: S112
                continue

            # Confidence decreases with missing data
            confidence = 1.0 - (missing_count / max(len(self._feature_columns), 1))

            values.append(
                SignalValue(ticker=symbol, score=prediction, confidence=confidence)
            )

        return values
