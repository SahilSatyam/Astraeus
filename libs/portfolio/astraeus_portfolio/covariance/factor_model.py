"""Factor-model covariance estimator: B × F × B' + D."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from astraeus_portfolio.contracts import CovarianceConfig, CovarianceResult
from astraeus_portfolio.covariance.base import CovarianceEstimator
from astraeus_portfolio.covariance.utils import nearest_psd, validate_returns


class FactorModelEstimator(CovarianceEstimator):
    """Covariance estimator using a factor model decomposition.

    Computes the covariance matrix as:

        Sigma = B @ F @ B.T + D

    where:
        B: (n × k) factor loading matrix mapping assets to factors
        F: (k × k) factor covariance matrix
        D: (n × n) diagonal idiosyncratic variance matrix

    The factor loading matrix B, factor covariance F, and idiosyncratic
    variance D are injected via the constructor since they are not derivable
    from the returns matrix alone.

    Args:
        factor_loadings: (n × k) factor loading matrix.
        factor_covariance: (k × k) factor covariance matrix.
        idiosyncratic_variance: Either an (n,) vector of per-asset
            idiosyncratic variances (diagonal entries) or an (n × n)
            diagonal matrix.
    """

    def __init__(
        self,
        factor_loadings: np.ndarray,
        factor_covariance: np.ndarray,
        idiosyncratic_variance: np.ndarray,
    ) -> None:
        self._validate_inputs(factor_loadings, factor_covariance, idiosyncratic_variance)
        self._B = factor_loadings
        self._F = factor_covariance
        # Accept either a 1-D vector or a 2-D diagonal matrix
        if idiosyncratic_variance.ndim == 1:
            self._D = np.diag(idiosyncratic_variance)
        else:
            self._D = idiosyncratic_variance

    def estimate(
        self, returns: np.ndarray, config: CovarianceConfig
    ) -> CovarianceResult:
        """Estimate covariance using the factor model B × F × B' + D.

        Args:
            returns: T×n matrix of daily returns. Used for validation and
                metadata (n_observations) but the covariance is computed
                from the injected factor model parameters.
            config: Estimation configuration including eigenvalue floor.

        Returns:
            CovarianceResult with PSD-corrected covariance matrix.

        Raises:
            ValueError: If returns fail validity checks or dimensions
                are inconsistent with the factor model parameters.
        """
        validate_returns(returns)

        t, n = returns.shape

        # Verify dimension consistency between returns and factor model
        if self._B.shape[0] != n:
            msg = (
                f"Factor loading matrix has {self._B.shape[0]} rows but "
                f"returns matrix has {n} assets. Dimensions must match."
            )
            raise ValueError(msg)

        # Compute factor-model covariance: B @ F @ B' + D
        sigma = self._B @ self._F @ self._B.T + self._D

        # Pass through nearest-PSD correction
        sigma = nearest_psd(sigma, floor=config.eigenvalue_floor)

        # Compute condition number for diagnostics
        eigenvalues = np.linalg.eigvalsh(sigma)
        condition_number = float(eigenvalues[-1] / eigenvalues[0])

        return CovarianceResult(
            matrix=sigma,
            estimator="factor_model",
            n_assets=n,
            n_observations=t,
            condition_number=condition_number,
            shrinkage_intensity=None,
            as_of_ts=datetime.now(tz=timezone.utc),
        )

    @staticmethod
    def _validate_inputs(
        factor_loadings: np.ndarray,
        factor_covariance: np.ndarray,
        idiosyncratic_variance: np.ndarray,
    ) -> None:
        """Validate factor model input dimensions and properties.

        Raises:
            ValueError: If inputs have invalid dimensions or properties.
        """
        # Factor loadings: must be 2-D (n × k)
        if factor_loadings.ndim != 2:
            msg = (
                f"Factor loading matrix must be 2-D, "
                f"got {factor_loadings.ndim}-D array."
            )
            raise ValueError(msg)

        n, k = factor_loadings.shape

        # Factor covariance: must be 2-D (k × k)
        if factor_covariance.ndim != 2:
            msg = (
                f"Factor covariance matrix must be 2-D, "
                f"got {factor_covariance.ndim}-D array."
            )
            raise ValueError(msg)

        if factor_covariance.shape != (k, k):
            msg = (
                f"Factor covariance matrix must be ({k}, {k}) to match "
                f"{k} factors, got shape {factor_covariance.shape}."
            )
            raise ValueError(msg)

        # Idiosyncratic variance: either (n,) vector or (n, n) diagonal
        if idiosyncratic_variance.ndim == 1:
            if idiosyncratic_variance.shape[0] != n:
                msg = (
                    f"Idiosyncratic variance vector must have {n} elements "
                    f"to match {n} assets, got {idiosyncratic_variance.shape[0]}."
                )
                raise ValueError(msg)
            if np.any(idiosyncratic_variance < 0):
                msg = "Idiosyncratic variance values must be non-negative."
                raise ValueError(msg)
        elif idiosyncratic_variance.ndim == 2:
            if idiosyncratic_variance.shape != (n, n):
                msg = (
                    f"Idiosyncratic variance matrix must be ({n}, {n}) "
                    f"to match {n} assets, got shape {idiosyncratic_variance.shape}."
                )
                raise ValueError(msg)
        else:
            msg = (
                f"Idiosyncratic variance must be 1-D (n,) or 2-D (n, n), "
                f"got {idiosyncratic_variance.ndim}-D array."
            )
            raise ValueError(msg)
