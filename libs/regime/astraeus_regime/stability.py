"""Regime stability filter.

A regime label only commits if probability > threshold for >= N consecutive days.
This prevents regime flip-flopping from noisy daily predictions.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date

import structlog

logger = structlog.get_logger("astraeus.regime.stability")


@dataclass
class StabilityEntry:
    """A single day's regime observation."""

    label: str
    probability: float
    run_date: date


class StabilityFilter:
    """Filters regime labels for temporal stability.

    Only commits a regime label when it has been the dominant prediction
    for at least `threshold_days` consecutive days with probability above
    `probability_threshold`.
    """

    def __init__(
        self,
        threshold_days: int = 3,
        probability_threshold: float = 0.6,
        max_history: int = 30,
    ) -> None:
        self._threshold_days = threshold_days
        self._prob_threshold = probability_threshold
        self._history: deque[StabilityEntry] = deque(maxlen=max_history)
        self._committed_label: str = "uncertain"
        self._consecutive_days: int = 0

    def update(self, label: str, probability: float, run_date: date) -> tuple[str, int]:
        """Update the filter with a new observation.

        Args:
            label: Raw regime label from the detector.
            probability: Confidence probability.
            run_date: Date of this observation.

        Returns:
            Tuple of (committed_label, stability_days).
        """
        entry = StabilityEntry(label=label, probability=probability, run_date=run_date)
        self._history.append(entry)

        # Count consecutive days with same label above threshold
        if label == self._get_last_label() and probability >= self._prob_threshold:
            self._consecutive_days += 1
        else:
            self._consecutive_days = 1 if probability >= self._prob_threshold else 0

        # Commit if stability threshold met
        if self._consecutive_days >= self._threshold_days:
            if label != self._committed_label:
                logger.info(
                    "regime_label_committed",
                    new_label=label,
                    old_label=self._committed_label,
                    stability_days=self._consecutive_days,
                    probability=round(probability, 3),
                )
            self._committed_label = label

        return self._committed_label, self._consecutive_days

    def _get_last_label(self) -> str | None:
        """Get the previous day's label."""
        if len(self._history) < 2:
            return None
        return self._history[-2].label

    @property
    def committed_label(self) -> str:
        """Current committed regime label."""
        return self._committed_label

    @property
    def consecutive_days(self) -> int:
        """Number of consecutive days at current raw label."""
        return self._consecutive_days

    def reset(self) -> None:
        """Reset the filter state."""
        self._history.clear()
        self._committed_label = "uncertain"
        self._consecutive_days = 0
