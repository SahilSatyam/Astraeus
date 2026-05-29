"""Property test for covariance PSD invariant.

**Validates: Requirements 1.5**

Property 1: For ANY valid return matrix generated via Hypothesis strategies,
ALL three covariance estimators (Sample, Ledoit-Wolf, Factor-Model) produce
a matrix where:
- All eigenvalues >= the configured eigenvalue floor (1e-8)
- The output matrix is symmetric (matrix == matrix.T within tolerance)
- The output matrix has shape (n, n) where n is the number of assets
"""

from __future__ import annotations

import numpy as np
import hypothesis.strategies as st
from hypothesis import given, settings, assume

from astraeus_portfolio.contracts import CovarianceConfig
from astraeus_portfolio.covariance.sample import SampleCovarianceEstimator
from astraeus_portfolio.covariance.ledoit_wolf import LedoitWolfEstimator
from astraeus_portfolio.covariance.factor_model import FactorModelEstimator


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

EIGENVALUE_FLOOR = 1e-8
DEFAULT_CONFIG = CovarianceConfig(eigenvalue_floor=EIGENVALUE_FLOOR)


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def st_valid_returns(draw: st.DrawFn) -> np.ndarray:
    """Generate a valid T×n return matrix with T >= n+1, no NaN/Inf.

    Constrains:
    - n in [2, 10] (number of assets)
    - T in [n+1, n+50] (number of observations)
    - Values are realistic daily returns in [-0.20, 0.20]
    """
    n = draw(st.integers(min_value=2, max_value=10))
    t = draw(st.integers(min_value=n + 1, max_value=n + 50))

    # Generate return values in a realistic range
    returns = draw(
        st.lists(
            st.lists(
                st.floats(min_value=-0.20, max_value=0.20, allow_nan=False, allow_infinity=False),
                min_size=n,
                max_size=n,
            ),
            min_size=t,
            max_size=t,
        )
    )
    return np.array(returns, dtype=np.float64)


@st.composite
def st_factor_model_inputs(draw: st.DrawFn) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Generate valid (returns, B, F, D) for the factor model estimator.

    Returns:
        Tuple of (returns, factor_loadings, factor_covariance, idiosyncratic_variance)
    """
    n = draw(st.integers(min_value=2, max_value=10))
    k = draw(st.integers(min_value=1, max_value=min(n, 5)))
    t = draw(st.integers(min_value=n + 1, max_value=n + 50))

    # Generate returns matrix
    returns = draw(
        st.lists(
            st.lists(
                st.floats(min_value=-0.20, max_value=0.20, allow_nan=False, allow_infinity=False),
                min_size=n,
                max_size=n,
            ),
            min_size=t,
            max_size=t,
        )
    )
    returns_arr = np.array(returns, dtype=np.float64)

    # Factor loadings B: (n × k) with realistic values
    b_values = draw(
        st.lists(
            st.lists(
                st.floats(min_value=-2.0, max_value=2.0, allow_nan=False, allow_infinity=False),
                min_size=k,
                max_size=k,
            ),
            min_size=n,
            max_size=n,
        )
    )
    B = np.array(b_values, dtype=np.float64)

    # Factor covariance F: (k × k) - generate as A'A to ensure PSD
    a_values = draw(
        st.lists(
            st.lists(
                st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
                min_size=k,
                max_size=k,
            ),
            min_size=k,
            max_size=k,
        )
    )
    A = np.array(a_values, dtype=np.float64)
    F = A.T @ A + 1e-6 * np.eye(k)  # Ensure strictly positive definite

    # Idiosyncratic variance D: (n,) positive values
    d_values = draw(
        st.lists(
            st.floats(min_value=1e-6, max_value=0.01, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        )
    )
    D = np.array(d_values, dtype=np.float64)

    return returns_arr, B, F, D


# ---------------------------------------------------------------------------
# Property 1: Covariance PSD invariant
# ---------------------------------------------------------------------------


class TestCovariancePSDInvariant:
    """Property 1: Covariance PSD invariant.

    **Validates: Requirements 1.5**

    For any valid return matrix, all three covariance estimators produce
    a symmetric n×n matrix with all eigenvalues >= eigenvalue floor (1e-8).
    """

    # --- Sample Covariance Estimator ---

    @given(returns=st_valid_returns())
    @settings(max_examples=200, deadline=None)
    def test_sample_eigenvalues_above_floor(self, returns: np.ndarray) -> None:
        """Sample estimator produces eigenvalues >= eigenvalue floor."""
        estimator = SampleCovarianceEstimator()
        result = estimator.estimate(returns, DEFAULT_CONFIG)

        eigenvalues = np.linalg.eigvalsh(result.matrix)
        assert np.all(eigenvalues >= EIGENVALUE_FLOOR - 1e-12), (
            f"Min eigenvalue {eigenvalues.min()} < floor {EIGENVALUE_FLOOR}"
        )

    @given(returns=st_valid_returns())
    @settings(max_examples=200, deadline=None)
    def test_sample_symmetric(self, returns: np.ndarray) -> None:
        """Sample estimator produces a symmetric matrix."""
        estimator = SampleCovarianceEstimator()
        result = estimator.estimate(returns, DEFAULT_CONFIG)

        np.testing.assert_allclose(
            result.matrix, result.matrix.T, atol=1e-12,
            err_msg="Sample covariance matrix is not symmetric",
        )

    @given(returns=st_valid_returns())
    @settings(max_examples=200, deadline=None)
    def test_sample_shape(self, returns: np.ndarray) -> None:
        """Sample estimator produces an (n, n) matrix."""
        n = returns.shape[1]
        estimator = SampleCovarianceEstimator()
        result = estimator.estimate(returns, DEFAULT_CONFIG)

        assert result.matrix.shape == (n, n), (
            f"Expected shape ({n}, {n}), got {result.matrix.shape}"
        )

    # --- Ledoit-Wolf Estimator ---

    @given(returns=st_valid_returns())
    @settings(max_examples=200, deadline=None)
    def test_ledoit_wolf_eigenvalues_above_floor(self, returns: np.ndarray) -> None:
        """Ledoit-Wolf estimator produces eigenvalues >= eigenvalue floor."""
        estimator = LedoitWolfEstimator()
        result = estimator.estimate(returns, DEFAULT_CONFIG)

        eigenvalues = np.linalg.eigvalsh(result.matrix)
        assert np.all(eigenvalues >= EIGENVALUE_FLOOR - 1e-12), (
            f"Min eigenvalue {eigenvalues.min()} < floor {EIGENVALUE_FLOOR}"
        )

    @given(returns=st_valid_returns())
    @settings(max_examples=200, deadline=None)
    def test_ledoit_wolf_symmetric(self, returns: np.ndarray) -> None:
        """Ledoit-Wolf estimator produces a symmetric matrix."""
        estimator = LedoitWolfEstimator()
        result = estimator.estimate(returns, DEFAULT_CONFIG)

        np.testing.assert_allclose(
            result.matrix, result.matrix.T, atol=1e-12,
            err_msg="Ledoit-Wolf covariance matrix is not symmetric",
        )

    @given(returns=st_valid_returns())
    @settings(max_examples=200, deadline=None)
    def test_ledoit_wolf_shape(self, returns: np.ndarray) -> None:
        """Ledoit-Wolf estimator produces an (n, n) matrix."""
        n = returns.shape[1]
        estimator = LedoitWolfEstimator()
        result = estimator.estimate(returns, DEFAULT_CONFIG)

        assert result.matrix.shape == (n, n), (
            f"Expected shape ({n}, {n}), got {result.matrix.shape}"
        )

    # --- Factor-Model Estimator ---

    @given(data=st_factor_model_inputs())
    @settings(max_examples=200, deadline=None)
    def test_factor_model_eigenvalues_above_floor(
        self, data: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]
    ) -> None:
        """Factor-model estimator produces eigenvalues >= eigenvalue floor."""
        returns, B, F, D = data
        estimator = FactorModelEstimator(
            factor_loadings=B,
            factor_covariance=F,
            idiosyncratic_variance=D,
        )
        result = estimator.estimate(returns, DEFAULT_CONFIG)

        eigenvalues = np.linalg.eigvalsh(result.matrix)
        assert np.all(eigenvalues >= EIGENVALUE_FLOOR - 1e-12), (
            f"Min eigenvalue {eigenvalues.min()} < floor {EIGENVALUE_FLOOR}"
        )

    @given(data=st_factor_model_inputs())
    @settings(max_examples=200, deadline=None)
    def test_factor_model_symmetric(
        self, data: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]
    ) -> None:
        """Factor-model estimator produces a symmetric matrix."""
        returns, B, F, D = data
        estimator = FactorModelEstimator(
            factor_loadings=B,
            factor_covariance=F,
            idiosyncratic_variance=D,
        )
        result = estimator.estimate(returns, DEFAULT_CONFIG)

        np.testing.assert_allclose(
            result.matrix, result.matrix.T, atol=1e-12,
            err_msg="Factor-model covariance matrix is not symmetric",
        )

    @given(data=st_factor_model_inputs())
    @settings(max_examples=200, deadline=None)
    def test_factor_model_shape(
        self, data: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]
    ) -> None:
        """Factor-model estimator produces an (n, n) matrix."""
        returns, B, F, D = data
        n = returns.shape[1]
        estimator = FactorModelEstimator(
            factor_loadings=B,
            factor_covariance=F,
            idiosyncratic_variance=D,
        )
        result = estimator.estimate(returns, DEFAULT_CONFIG)

        assert result.matrix.shape == (n, n), (
            f"Expected shape ({n}, {n}), got {result.matrix.shape}"
        )
