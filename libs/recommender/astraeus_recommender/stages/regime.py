"""Stage 2: Regime Detection — classifies current market regime.

Wraps the astraeus_regime library (HMM + GMM) and applies the stability filter.
A regime label only commits if probability > threshold for >= 3 consecutive days.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from ..contracts import DailyInputSnapshot, RegimeDetection, RegimeLabel

if TYPE_CHECKING:
    from astraeus_regime import RegimeDetector

logger = structlog.get_logger("astraeus.recommender.stages.regime")


class RegimeStage:
    """Stage 2: Market regime classification.

    Uses HMM for temporal structure and GMM for cross-sectional clustering.
    Applies a stability filter before committing a regime label.
    """

    def __init__(
        self,
        detector: RegimeDetector,
        stability_threshold_days: int = 3,
        probability_threshold: float = 0.6,
    ) -> None:
        self._detector = detector
        self._stability_days = stability_threshold_days
        self._prob_threshold = probability_threshold

    async def run(
        self,
        run_id: UUID,
        snapshot: DailyInputSnapshot,
    ) -> RegimeDetection:
        """Execute Stage 2: detect market regime from aggregated features.

        Args:
            run_id: Pipeline run identifier.
            snapshot: Stage 1 output with feature matrix.

        Returns:
            RegimeDetection with label, probability, and stability info.
        """
        start = time.perf_counter()

        logger.info("stage2_regime_start", run_id=str(run_id))

        # Extract macro/vol features for regime detection
        macro_features = self._extract_macro_features(snapshot)

        # Run HMM detection
        result = await self._detector.detect(
            features=macro_features,
            run_date=snapshot.run_date,
        )

        # Map detector output to our contract
        label = self._map_label(result.label)
        probability = result.probability
        stability_days = result.stability_days

        # Apply stability filter: if below threshold, fall back to UNCERTAIN
        if probability < self._prob_threshold or stability_days < self._stability_days:
            logger.warning(
                "stage2_regime_unstable",
                run_id=str(run_id),
                raw_label=label,
                probability=probability,
                stability_days=stability_days,
            )
            label = RegimeLabel.UNCERTAIN

        elapsed_ms = (time.perf_counter() - start) * 1000

        detection = RegimeDetection(
            run_id=run_id,
            label=label,
            probability=probability,
            stability_days=stability_days,
            model=result.model_version,
            hmm_state_probs=result.state_probabilities,
            gmm_cluster=result.gmm_cluster,
        )

        logger.info(
            "stage2_regime_complete",
            run_id=str(run_id),
            label=label,
            probability=round(probability, 3),
            stability_days=stability_days,
            elapsed_ms=round(elapsed_ms, 1),
        )

        return detection

    def _extract_macro_features(
        self, snapshot: DailyInputSnapshot
    ) -> dict[str, list[float]]:
        """Extract macro/vol features from the snapshot for regime detection.

        Returns a dict of feature_name -> list of values across symbols.
        """
        macro_prefixes = ("vix", "vol_", "macro_", "spread_", "rate_")
        result: dict[str, list[float]] = {}

        for feature_name in snapshot.feature_names:
            if any(feature_name.startswith(p) for p in macro_prefixes):
                values = []
                for symbol in snapshot.symbols:
                    val = snapshot.feature_matrix.get(symbol, {}).get(feature_name)
                    if val is not None:
                        values.append(val)
                if values:
                    result[feature_name] = values

        return result

    @staticmethod
    def _map_label(raw_label: str) -> RegimeLabel:
        """Map raw detector label to our enum."""
        label_map = {
            "risk_on": RegimeLabel.RISK_ON,
            "risk_off": RegimeLabel.RISK_OFF,
            "vol_spike": RegimeLabel.VOL_SPIKE,
            "mean_reversion": RegimeLabel.MEAN_REVERSION,
            "trending": RegimeLabel.TRENDING,
        }
        return label_map.get(raw_label, RegimeLabel.UNCERTAIN)
