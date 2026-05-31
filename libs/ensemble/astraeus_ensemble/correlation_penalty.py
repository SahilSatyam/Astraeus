"""Correlation penalty for ensemble signal combination.

Penalizes the composite score when multiple signals are highly correlated,
preventing double-counting of the same information source.
"""

from __future__ import annotations

import numpy as np
import structlog

logger = structlog.get_logger("astraeus.ensemble.correlation_penalty")


class CorrelationPenalty:
    """Applies a penalty based on inter-signal correlation.

    When two signals are highly correlated (e.g., technical momentum and
    ML momentum), their combined contribution should be discounted to avoid
    double-counting the same alpha source.
    """

    def __init__(
        self,
        penalty_threshold: float = 0.7,
        max_penalty: float = 0.3,
    ) -> None:
        """Initialize the correlation penalty.

        Args:
            penalty_threshold: Correlation above this triggers a penalty.
            max_penalty: Maximum penalty factor (0 = no penalty, 1 = full discount).
        """
        self._threshold = penalty_threshold
        self._max_penalty = max_penalty
        # Historical signal correlations (updated periodically)
        self._correlation_matrix: dict[tuple[str, str], float] = {}

    def update_correlations(self, signal_scores: dict[str, dict[str, float]]) -> None:
        """Update the correlation matrix from recent signal scores.

        Args:
            signal_scores: signal_name -> {ticker: score} for recent period.
        """
        signals = sorted(signal_scores.keys())
        if len(signals) < 2:
            return

        # Build score matrix: (n_tickers, n_signals)
        all_tickers: set[str] = set()
        for scores in signal_scores.values():
            all_tickers.update(scores.keys())
        tickers = sorted(all_tickers)

        if len(tickers) < 5:
            return

        matrix = np.zeros((len(tickers), len(signals)))
        for j, signal in enumerate(signals):
            for i, ticker in enumerate(tickers):
                matrix[i, j] = signal_scores[signal].get(ticker, 0.0)

        # Compute pairwise correlations
        corr = np.corrcoef(matrix.T)

        for i, sig_i in enumerate(signals):
            for j, sig_j in enumerate(signals):
                if i < j:
                    corr_val = float(corr[i, j]) if corr.ndim == 2 else float(corr)
                    self._correlation_matrix[(sig_i, sig_j)] = corr_val
                    self._correlation_matrix[(sig_j, sig_i)] = corr_val

        logger.debug(
            "correlations_updated",
            n_pairs=len(self._correlation_matrix),
        )

    def compute_penalty(self, attributions: dict[str, float]) -> float:
        """Compute the correlation penalty for a set of signal attributions.

        Args:
            attributions: signal_name -> weighted contribution for one ticker.

        Returns:
            Penalty factor in [0, max_penalty]. Higher = more discount.
        """
        active_signals = [s for s, v in attributions.items() if abs(v) > 1e-6]

        if len(active_signals) < 2:
            return 0.0

        # Find max pairwise correlation among active signals
        max_corr = 0.0
        for i, sig_i in enumerate(active_signals):
            for sig_j in active_signals[i + 1 :]:
                corr = abs(self._correlation_matrix.get((sig_i, sig_j), 0.0))
                max_corr = max(max_corr, corr)

        # Apply penalty if above threshold
        if max_corr <= self._threshold:
            return 0.0

        # Linear penalty between threshold and 1.0
        excess = (max_corr - self._threshold) / (1.0 - self._threshold)
        penalty = excess * self._max_penalty

        return min(penalty, self._max_penalty)
