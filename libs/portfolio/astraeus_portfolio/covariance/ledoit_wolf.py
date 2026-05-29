"""Ledoit-Wolf shrinkage covariance estimator.

Implements the Ledoit & Wolf (2004) closed-form optimal shrinkage intensity
toward a scaled identity target. The shrinkage intensity minimizes the
expected Frobenius loss between the true covariance and the shrunk estimator.

Reference:
    Ledoit, O. and Wolf, M. (2004). "A well-conditioned estimator for
    large-dimensional covariance matrices." Journal of Multivariate Analysis,
    88(2), 365-411.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from astraeus_portfolio.contracts import CovarianceConfig, CovarianceResult
from astraeus_portfolio.covariance.base import CovarianceEstimator
from astraeus_portfolio.covariance.utils import nearest_psd, validate_returns


class LedoitWolfEstimator(CovarianceEstimator):
    """Ledoit-Wolf shrinkage covariance estimator.

    Shrinks the sample covariance matrix toward a scaled identity target
    using the closed-form optimal shrinkage intensity from Ledoit & Wolf (2004).

    The shrinkage target is F = mu * I_n where mu = trace(S) / n, and the
    optimal shrinkage intensity alpha minimizes the expected Frobenius loss.
    """

    def estimate(self, returns: np.ndarray, config: CovarianceConfig) -> CovarianceResult:
        """Estimate covariance using Ledoit-Wolf shrinkage.

        Args:
            returns: T×n matrix of daily returns (no NaN/Inf, T >= n+1).
            config: Estimation configuration including eigenvalue floor.

        Returns:
            CovarianceResult with PSD-corrected shrunk covariance matrix
            and the computed shrinkage intensity.

        Raises:
            ValueError: If returns fail validity checks.
        """
        validate_returns(returns)

        t, n = returns.shape

        # Compute sample covariance (bias-corrected, ddof=1)
        sample_cov = np.cov(returns, rowvar=False)

        # Ensure 2-D even for single-asset case
        sample_cov = np.atleast_2d(sample_cov)

        # Compute shrinkage target: scaled identity F = mu * I_n
        mu = np.trace(sample_cov) / n
        target = mu * np.eye(n)

        # Compute optimal shrinkage intensity using Ledoit-Wolf (2004)
        alpha = self._compute_shrinkage_intensity(returns, sample_cov, mu, t, n)

        # Shrunk covariance: alpha * F + (1 - alpha) * S
        shrunk = alpha * target + (1.0 - alpha) * sample_cov

        # Pass through nearest PSD correction
        psd_matrix = nearest_psd(shrunk, floor=config.eigenvalue_floor)

        # Compute condition number
        condition_number = float(np.linalg.cond(psd_matrix))

        return CovarianceResult(
            matrix=psd_matrix,
            estimator="ledoit_wolf",
            n_assets=n,
            n_observations=t,
            condition_number=condition_number,
            shrinkage_intensity=float(alpha),
            as_of_ts=datetime.now(tz=UTC),
        )

    @staticmethod
    def _compute_shrinkage_intensity(
        returns: np.ndarray,
        sample_cov: np.ndarray,
        mu: float,
        t: int,
        n: int,
    ) -> float:
        """Compute the Ledoit-Wolf (2004) closed-form optimal shrinkage intensity.

        The formula minimizes E[||alpha*F + (1-alpha)*S - Sigma||_F^2] where
        F = mu*I is the shrinkage target and S is the sample covariance.

        Uses the Oracle Approximating Shrinkage (OAS) variant of the
        Ledoit-Wolf formula for computational efficiency.

        Args:
            returns: T×n return matrix.
            sample_cov: n×n sample covariance matrix.
            mu: Trace of sample_cov divided by n (target scaling).
            t: Number of observations.
            n: Number of assets.

        Returns:
            Optimal shrinkage intensity clamped to [0, 1].
        """
        # De-mean the returns
        x = returns - returns.mean(axis=0)

        # Compute the squared Frobenius norm of (S - F)
        # This is the denominator: measures how far S is from the target
        delta = sample_cov - mu * np.eye(n)
        delta_sq_sum = np.sum(delta**2)

        if delta_sq_sum < 1e-16:
            # Sample covariance is already proportional to identity
            return 0.0

        # Compute pi: sum of asymptotic variances of sample covariance entries
        # pi = (1/T^2) * sum_t ||x_t x_t' - S||_F^2
        # Efficient vectorized computation
        # For each observation x_t: compute x_t * x_t' and compare to S
        # ||x_t x_t' - S||_F^2 = sum_{i,j} (x_ti * x_tj - S_ij)^2
        pi_sum = 0.0
        for k in range(t):
            x_k = x[k, :]
            outer_k = np.outer(x_k, x_k)
            diff = outer_k - sample_cov
            pi_sum += np.sum(diff**2)

        pi_hat = pi_sum / t

        # Ledoit-Wolf (2004) optimal shrinkage intensity:
        # alpha* = pi_hat / (T * delta_sq_sum)
        # where pi_hat estimates the total squared estimation error of S
        # and delta_sq_sum measures the distance between S and the target
        alpha = pi_hat / (t * delta_sq_sum)

        # Clamp to [0, 1]
        return float(min(1.0, max(0.0, alpha)))
