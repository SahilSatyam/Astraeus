"""HMM-based regime detection.

Uses hmmlearn's GaussianHMM to model market regimes as hidden states.
The model is fitted on macro/vol features with rolling refit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger("astraeus.regime.hmm")

# Default state labels ordered by typical risk profile
DEFAULT_STATE_LABELS = ["risk_on", "trending", "mean_reversion", "risk_off", "vol_spike"]


@dataclass
class HMMResult:
    """Result from HMM prediction."""

    label: str
    probability: float
    state_probabilities: dict[str, float] = field(default_factory=dict)
    state_index: int = 0


class HMMRegimeModel:
    """Gaussian HMM for market regime detection.

    States are mapped to semantic labels based on their emission parameters:
    - Low vol + positive returns → risk_on
    - High vol + negative returns → vol_spike / risk_off
    - Moderate vol + mean-reverting → mean_reversion
    """

    def __init__(
        self,
        n_states: int = 5,
        covariance_type: str = "full",
        n_iter: int = 100,
        random_state: int = 42,
    ) -> None:
        self._n_states = n_states
        self._covariance_type = covariance_type
        self._n_iter = n_iter
        self._random_state = random_state
        self._model: Any = None
        self._state_labels = DEFAULT_STATE_LABELS[:n_states]
        self._fitted = False

    @property
    def version(self) -> str:
        return "hmm_v1"

    def fit(self, historical_features: dict[str, list[list[float]]]) -> None:
        """Fit the HMM on historical feature data.

        Args:
            historical_features: feature_name -> list of daily value vectors.
        """
        from hmmlearn.hmm import GaussianHMM

        # Build observation matrix: (n_days, n_features)
        X = self._build_matrix(historical_features)
        if X is None or len(X) < self._n_states * 10:
            logger.warning("hmm_insufficient_data", n_obs=len(X) if X is not None else 0)
            return

        self._model = GaussianHMM(
            n_components=self._n_states,
            covariance_type=self._covariance_type,
            n_iter=self._n_iter,
            random_state=self._random_state,
        )
        self._model.fit(X)
        self._fitted = True

        # Assign semantic labels based on emission means
        self._assign_labels()

        logger.info(
            "hmm_fitted",
            n_states=self._n_states,
            n_observations=len(X),
            converged=self._model.monitor_.converged,
        )

    def predict(self, features: dict[str, list[float]]) -> HMMResult:
        """Predict the current regime state.

        Args:
            features: Current day's feature values.

        Returns:
            HMMResult with label and probabilities.
        """
        if not self._fitted or self._model is None:
            # Return default uncertain state if not fitted
            return HMMResult(
                label="uncertain",
                probability=0.0,
                state_probabilities=dict.fromkeys(self._state_labels, 1.0 / self._n_states),
            )

        # Build single observation vector
        X = self._build_single_observation(features)
        if X is None:
            return HMMResult(label="uncertain", probability=0.0)

        # Get state probabilities
        log_prob, posteriors = self._model.score_samples(X)
        state_probs = posteriors[-1]  # Last observation's posterior

        # Most likely state
        state_idx = int(np.argmax(state_probs))
        label = (
            self._state_labels[state_idx] if state_idx < len(self._state_labels) else "uncertain"
        )
        probability = float(state_probs[state_idx])

        state_probabilities = {
            self._state_labels[i]: float(state_probs[i])
            for i in range(min(len(state_probs), len(self._state_labels)))
        }

        return HMMResult(
            label=label,
            probability=probability,
            state_probabilities=state_probabilities,
            state_index=state_idx,
        )

    def _build_matrix(self, features: dict[str, list[list[float]]]) -> np.ndarray | None:
        """Build observation matrix from historical features."""
        if not features:
            return None

        # Each feature contributes one column; aggregate across symbols via mean
        columns = []
        for _name, daily_values in sorted(features.items()):
            # daily_values is list of lists (one per day, values across symbols)
            col = [np.mean(day_vals) if day_vals else 0.0 for day_vals in daily_values]
            columns.append(col)

        if not columns:
            return None

        # Align lengths
        min_len = min(len(c) for c in columns)
        X = np.column_stack([np.array(c[:min_len]) for c in columns])
        return X

    def _build_single_observation(self, features: dict[str, list[float]]) -> np.ndarray | None:
        """Build a single observation vector from current features."""
        if not features:
            return None

        values = []
        for _name in sorted(features.keys()):
            vals = features[_name]
            values.append(np.mean(vals) if vals else 0.0)

        return np.array([values])

    def _assign_labels(self) -> None:
        """Assign semantic labels to states based on emission parameters.

        Heuristic: sort states by mean of first feature (typically volatility-related).
        Low mean → risk_on, high mean → vol_spike.
        """
        if self._model is None:
            return

        means = self._model.means_
        # Sort by first feature mean (assumed to be vol-related)
        order = np.argsort(means[:, 0])

        # Reassign labels: lowest vol → risk_on, highest → vol_spike
        base_labels = ["risk_on", "trending", "mean_reversion", "risk_off", "vol_spike"]
        self._state_labels = [
            base_labels[i] if i < len(base_labels) else f"state_{i}" for i in range(self._n_states)
        ]
        # Reorder based on volatility sorting
        reordered = [""] * self._n_states
        for new_idx, old_idx in enumerate(order):
            if new_idx < len(base_labels):
                reordered[old_idx] = base_labels[new_idx]
            else:
                reordered[old_idx] = f"state_{new_idx}"
        self._state_labels = reordered
