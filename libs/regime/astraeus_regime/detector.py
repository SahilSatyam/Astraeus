"""Regime detector — combines HMM and GMM for robust classification.

The HMM provides temporal structure (state persistence over time).
The GMM provides cross-sectional clustering for validation.
The stability filter prevents regime flip-flopping.
"""

from __future__ import annotations

from datetime import date

import structlog
from pydantic import BaseModel, Field

from .gmm import GMMClusterer
from .hmm import HMMRegimeModel
from .stability import StabilityFilter

logger = structlog.get_logger("astraeus.regime.detector")


class RegimeResult(BaseModel):
    """Output from the regime detector."""

    label: str
    probability: float = Field(ge=0.0, le=1.0)
    stability_days: int = Field(ge=0)
    model_version: str = "hmm_v1"
    state_probabilities: dict[str, float] = Field(default_factory=dict)
    gmm_cluster: str | None = None


class RegimeDetector:
    """Combined HMM + GMM regime detector with stability filtering.

    Usage:
        detector = RegimeDetector(n_states=5)
        result = await detector.detect(features, run_date)
    """

    def __init__(
        self,
        n_states: int = 5,
        stability_threshold_days: int = 3,
        probability_threshold: float = 0.6,
        hmm_model: HMMRegimeModel | None = None,
        gmm_model: GMMClusterer | None = None,
    ) -> None:
        self._hmm = hmm_model or HMMRegimeModel(n_states=n_states)
        self._gmm = gmm_model or GMMClusterer(n_clusters=n_states)
        self._stability = StabilityFilter(
            threshold_days=stability_threshold_days,
            probability_threshold=probability_threshold,
        )
        self._n_states = n_states

    async def detect(
        self,
        features: dict[str, list[float]],
        run_date: date,
    ) -> RegimeResult:
        """Detect the current market regime.

        Args:
            features: Dict of feature_name -> list of values (macro/vol features).
            run_date: Current trading date.

        Returns:
            RegimeResult with label, probability, and stability info.
        """
        logger.info("regime_detect_start", run_date=run_date.isoformat())

        # Run HMM for temporal regime classification
        hmm_result = self._hmm.predict(features)

        # Run GMM for cross-sectional validation
        gmm_cluster = self._gmm.predict(features)

        # Apply stability filter
        stable_label, stability_days = self._stability.update(
            label=hmm_result.label,
            probability=hmm_result.probability,
            run_date=run_date,
        )

        result = RegimeResult(
            label=stable_label,
            probability=hmm_result.probability,
            stability_days=stability_days,
            model_version=self._hmm.version,
            state_probabilities=hmm_result.state_probabilities,
            gmm_cluster=gmm_cluster,
        )

        logger.info(
            "regime_detect_complete",
            label=stable_label,
            probability=round(hmm_result.probability, 3),
            stability_days=stability_days,
            gmm_cluster=gmm_cluster,
        )

        return result

    def fit(self, historical_features: dict[str, list[list[float]]]) -> None:
        """Fit the HMM and GMM on historical data.

        Args:
            historical_features: Dict of feature_name -> list of daily value lists.
        """
        self._hmm.fit(historical_features)
        self._gmm.fit(historical_features)
        logger.info("regime_models_fitted")
