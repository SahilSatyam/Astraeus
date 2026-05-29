"""CovarianceEstimator ABC."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from astraeus_portfolio.contracts import CovarianceConfig, CovarianceResult


class CovarianceEstimator(ABC):
    """Abstract base class for covariance estimation methods.

    All concrete estimators implement the `estimate` method which accepts
    a T×n daily return matrix and a configuration object, returning a
    CovarianceResult with a PSD-corrected covariance matrix.
    """

    @abstractmethod
    def estimate(
        self, returns: np.ndarray, config: CovarianceConfig
    ) -> CovarianceResult:
        """Estimate covariance from a daily return matrix (T×n).

        Args:
            returns: T×n matrix of daily returns (no NaN/Inf, T >= n+1).
            config: Estimation configuration including window size and
                eigenvalue floor.

        Returns:
            CovarianceResult with a PSD-corrected n×n covariance matrix.

        Raises:
            ValueError: If returns fail validity checks (NaN/Inf present,
                insufficient observations, or dimension mismatch).
        """
        ...
