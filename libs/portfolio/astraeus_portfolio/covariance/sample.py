"""Sample covariance estimator."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from astraeus_portfolio.contracts import CovarianceConfig, CovarianceResult
from astraeus_portfolio.covariance.base import CovarianceEstimator
from astraeus_portfolio.covariance.utils import nearest_psd, validate_returns


class SampleCovarianceEstimator(CovarianceEstimator):
    """Estimate covariance using the unbiased sample covariance matrix.

    Computes the standard sample covariance from a T×n daily return matrix,
    then passes the result through nearest_psd to guarantee positive
    semi-definiteness with a configurable eigenvalue floor.
    """

    def estimate(self, returns: np.ndarray, config: CovarianceConfig) -> CovarianceResult:
        """Estimate sample covariance from a daily return matrix (T×n).

        Args:
            returns: T×n matrix of daily returns (no NaN/Inf, T >= n+1).
            config: Estimation configuration including eigenvalue floor.

        Returns:
            CovarianceResult with a PSD-corrected n×n covariance matrix,
            estimator="sample", and shrinkage_intensity=None.

        Raises:
            ValueError: If returns fail validity checks (NaN/Inf present,
                insufficient observations, or dimension mismatch).
        """
        validate_returns(returns)

        t, n = returns.shape

        # Compute unbiased sample covariance (ddof=1 is the default for np.cov)
        cov = np.cov(returns, rowvar=False)

        # Ensure 2-D even for single-asset case
        cov = np.atleast_2d(cov)

        # Project to nearest PSD matrix with eigenvalue floor
        cov_psd = nearest_psd(cov, floor=config.eigenvalue_floor)

        # Compute condition number
        condition_number = float(np.linalg.cond(cov_psd))

        return CovarianceResult(
            matrix=cov_psd,
            estimator="sample",
            n_assets=n,
            n_observations=t,
            condition_number=condition_number,
            shrinkage_intensity=None,
            as_of_ts=datetime.now(tz=UTC),
        )
