"""GMM-based cross-sectional clustering for regime validation.

Provides an independent regime signal via Gaussian Mixture Models
on a different feature subset than the HMM. Used for cross-validation
of the HMM regime label.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger("astraeus.regime.gmm")

# Cluster labels mapped by centroid characteristics
DEFAULT_CLUSTER_LABELS = [
    "low_vol_growth",
    "moderate_balanced",
    "high_vol_defensive",
    "crisis_flight",
    "recovery_rotation",
]


class GMMClusterer:
    """Gaussian Mixture Model for cross-sectional regime clustering.

    Clusters the current market state based on cross-sectional features
    (e.g., sector dispersion, correlation structure, breadth).
    """

    def __init__(
        self,
        n_clusters: int = 5,
        covariance_type: str = "full",
        random_state: int = 42,
    ) -> None:
        self._n_clusters = n_clusters
        self._covariance_type = covariance_type
        self._random_state = random_state
        self._model: Any = None
        self._cluster_labels = DEFAULT_CLUSTER_LABELS[:n_clusters]
        self._fitted = False

    def fit(self, historical_features: dict[str, list[list[float]]]) -> None:
        """Fit the GMM on historical cross-sectional features.

        Args:
            historical_features: feature_name -> list of daily value vectors.
        """
        from sklearn.mixture import GaussianMixture

        X = self._build_matrix(historical_features)
        if X is None or len(X) < self._n_clusters * 5:
            logger.warning("gmm_insufficient_data", n_obs=len(X) if X is not None else 0)
            return

        self._model = GaussianMixture(
            n_components=self._n_clusters,
            covariance_type=self._covariance_type,
            random_state=self._random_state,
            max_iter=200,
        )
        self._model.fit(X)
        self._fitted = True

        logger.info(
            "gmm_fitted",
            n_clusters=self._n_clusters,
            n_observations=len(X),
            converged=self._model.converged_,
        )

    def predict(self, features: dict[str, list[float]]) -> str | None:
        """Predict the current cluster label.

        Args:
            features: Current day's feature values.

        Returns:
            Cluster label string, or None if not fitted.
        """
        if not self._fitted or self._model is None:
            return None

        X = self._build_single_observation(features)
        if X is None:
            return None

        cluster_idx = int(self._model.predict(X)[0])
        if cluster_idx < len(self._cluster_labels):
            return self._cluster_labels[cluster_idx]
        return f"cluster_{cluster_idx}"

    def predict_proba(self, features: dict[str, list[float]]) -> dict[str, float]:
        """Get cluster membership probabilities.

        Returns:
            Dict of cluster_label -> probability.
        """
        if not self._fitted or self._model is None:
            return {}

        X = self._build_single_observation(features)
        if X is None:
            return {}

        probs = self._model.predict_proba(X)[0]
        return {
            self._cluster_labels[i] if i < len(self._cluster_labels) else f"cluster_{i}": float(p)
            for i, p in enumerate(probs)
        }

    def _build_matrix(self, features: dict[str, list[list[float]]]) -> np.ndarray | None:
        """Build observation matrix from historical features."""
        if not features:
            return None

        columns = []
        for _name, daily_values in sorted(features.items()):
            # Use cross-sectional statistics as features
            col_mean = [np.mean(dv) if dv else 0.0 for dv in daily_values]
            col_std = [np.std(dv) if len(dv) > 1 else 0.0 for dv in daily_values]
            columns.append(col_mean)
            columns.append(col_std)

        if not columns:
            return None

        min_len = min(len(c) for c in columns)
        X = np.column_stack([np.array(c[:min_len]) for c in columns])
        return X

    def _build_single_observation(self, features: dict[str, list[float]]) -> np.ndarray | None:
        """Build a single observation from current features."""
        if not features:
            return None

        values = []
        for _name in sorted(features.keys()):
            vals = features[_name]
            values.append(np.mean(vals) if vals else 0.0)
            values.append(np.std(vals) if len(vals) > 1 else 0.0)

        return np.array([values])
