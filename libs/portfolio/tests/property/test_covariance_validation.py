"""Property tests for covariance input validation.

**Validates: Requirements 1.6, 1.7**

These tests verify that ALL covariance estimators correctly reject invalid inputs:
- Return matrices containing NaN values raise ValueError with "NaN" in the message
- Return matrices containing Inf values raise ValueError with "Inf" in the message
- Return matrices with T < n+1 raise ValueError with "Insufficient observations"
- Non-2D arrays raise ValueError with "2-D" in the message

Uses Hypothesis to generate arbitrary invalid inputs and verifies that validation
is consistent across SampleCovarianceEstimator, LedoitWolfEstimator, and
FactorModelEstimator.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from astraeus_portfolio.contracts import CovarianceConfig
from astraeus_portfolio.covariance.factor_model import FactorModelEstimator
from astraeus_portfolio.covariance.ledoit_wolf import LedoitWolfEstimator
from astraeus_portfolio.covariance.sample import SampleCovarianceEstimator

# ---------------------------------------------------------------------------
# Shared configuration and estimator fixtures
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = CovarianceConfig()

# Estimators that require no constructor params
SIMPLE_ESTIMATORS = [
    SampleCovarianceEstimator(),
    LedoitWolfEstimator(),
]


def _make_factor_model_estimator(n: int, k: int = 3) -> FactorModelEstimator:
    """Create a FactorModelEstimator with valid factor model inputs for n assets."""
    rng = np.random.default_rng(42)
    factor_loadings = rng.standard_normal((n, k))
    factor_cov = np.eye(k) * 0.01
    idio_var = np.abs(rng.standard_normal(n)) * 0.001 + 1e-6
    return FactorModelEstimator(
        factor_loadings=factor_loadings,
        factor_covariance=factor_cov,
        idiosyncratic_variance=idio_var,
    )


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

# Strategy for valid matrix dimensions (small to keep tests fast)
st_n_assets = st.integers(min_value=2, max_value=10)
st_n_obs_sufficient = st.integers(min_value=3, max_value=50)


@st.composite
def st_valid_returns(draw: st.DrawFn) -> np.ndarray:
    """Generate a valid T×n return matrix (T >= n+1, no NaN/Inf)."""
    n = draw(st_n_assets)
    # Ensure T >= n + 1
    t = draw(st.integers(min_value=n + 1, max_value=n + 30))
    rng = np.random.default_rng(draw(st.integers(min_value=0, max_value=2**32 - 1)))
    return rng.standard_normal((t, n)) * 0.01


@st.composite
def st_returns_with_nan(draw: st.DrawFn) -> np.ndarray:
    """Generate a T×n return matrix with NaN injected at random positions."""
    n = draw(st_n_assets)
    t = draw(st.integers(min_value=n + 1, max_value=n + 30))
    rng = np.random.default_rng(draw(st.integers(min_value=0, max_value=2**32 - 1)))
    matrix = rng.standard_normal((t, n)) * 0.01

    # Inject at least one NaN at a random position
    num_nans = draw(st.integers(min_value=1, max_value=max(1, t * n // 4)))
    nan_positions = draw(
        st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=t - 1),
                st.integers(min_value=0, max_value=n - 1),
            ),
            min_size=num_nans,
            max_size=num_nans,
        )
    )
    for row, col in nan_positions:
        matrix[row, col] = np.nan

    return matrix


@st.composite
def st_returns_with_inf(draw: st.DrawFn) -> np.ndarray:
    """Generate a T×n return matrix with Inf injected at random positions."""
    n = draw(st_n_assets)
    t = draw(st.integers(min_value=n + 1, max_value=n + 30))
    rng = np.random.default_rng(draw(st.integers(min_value=0, max_value=2**32 - 1)))
    matrix = rng.standard_normal((t, n)) * 0.01

    # Inject at least one Inf (positive or negative) at random positions
    num_infs = draw(st.integers(min_value=1, max_value=max(1, t * n // 4)))
    inf_positions = draw(
        st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=t - 1),
                st.integers(min_value=0, max_value=n - 1),
            ),
            min_size=num_infs,
            max_size=num_infs,
        )
    )
    for row, col in inf_positions:
        # Randomly choose +Inf or -Inf
        sign = draw(st.sampled_from([1.0, -1.0]))
        matrix[row, col] = sign * np.inf

    return matrix


@st.composite
def st_returns_insufficient_obs(draw: st.DrawFn) -> np.ndarray:
    """Generate a T×n return matrix where T < n+1 (insufficient observations)."""
    n = draw(st.integers(min_value=2, max_value=10))
    # T must be strictly less than n + 1, so T <= n
    t = draw(st.integers(min_value=1, max_value=n))
    rng = np.random.default_rng(draw(st.integers(min_value=0, max_value=2**32 - 1)))
    return rng.standard_normal((t, n)) * 0.01


@st.composite
def st_non_2d_array(draw: st.DrawFn) -> np.ndarray:
    """Generate a 1-D or 3-D numpy array (not 2-D)."""
    ndim = draw(st.sampled_from([1, 3]))
    rng = np.random.default_rng(draw(st.integers(min_value=0, max_value=2**32 - 1)))

    if ndim == 1:
        size = draw(st.integers(min_value=2, max_value=20))
        return rng.standard_normal(size) * 0.01
    else:
        # 3-D array
        d1 = draw(st.integers(min_value=2, max_value=5))
        d2 = draw(st.integers(min_value=2, max_value=5))
        d3 = draw(st.integers(min_value=2, max_value=5))
        return rng.standard_normal((d1, d2, d3)) * 0.01


# ---------------------------------------------------------------------------
# Property 3: Covariance input validation
# ---------------------------------------------------------------------------


class TestCovarianceNaNValidation:
    """For ANY return matrix containing NaN values, ALL estimators raise ValueError.

    **Validates: Requirements 1.6, 1.7**
    """

    @given(returns=st_returns_with_nan())
    @settings(max_examples=100, deadline=None)
    def test_sample_estimator_rejects_nan(self, returns: np.ndarray) -> None:
        """SampleCovarianceEstimator raises ValueError with 'NaN' for NaN inputs."""
        estimator = SampleCovarianceEstimator()
        with pytest.raises(ValueError, match="NaN"):
            estimator.estimate(returns, DEFAULT_CONFIG)

    @given(returns=st_returns_with_nan())
    @settings(max_examples=100, deadline=None)
    def test_ledoit_wolf_estimator_rejects_nan(self, returns: np.ndarray) -> None:
        """LedoitWolfEstimator raises ValueError with 'NaN' for NaN inputs."""
        estimator = LedoitWolfEstimator()
        with pytest.raises(ValueError, match="NaN"):
            estimator.estimate(returns, DEFAULT_CONFIG)

    @given(returns=st_returns_with_nan())
    @settings(max_examples=100, deadline=None)
    def test_factor_model_estimator_rejects_nan(self, returns: np.ndarray) -> None:
        """FactorModelEstimator raises ValueError with 'NaN' for NaN inputs."""
        n = returns.shape[1]
        estimator = _make_factor_model_estimator(n)
        with pytest.raises(ValueError, match="NaN"):
            estimator.estimate(returns, DEFAULT_CONFIG)


class TestCovarianceInfValidation:
    """For ANY return matrix containing Inf values, ALL estimators raise ValueError.

    **Validates: Requirements 1.6, 1.7**
    """

    @given(returns=st_returns_with_inf())
    @settings(max_examples=100, deadline=None)
    def test_sample_estimator_rejects_inf(self, returns: np.ndarray) -> None:
        """SampleCovarianceEstimator raises ValueError with 'Inf' for Inf inputs."""
        estimator = SampleCovarianceEstimator()
        with pytest.raises(ValueError, match="Inf"):
            estimator.estimate(returns, DEFAULT_CONFIG)

    @given(returns=st_returns_with_inf())
    @settings(max_examples=100, deadline=None)
    def test_ledoit_wolf_estimator_rejects_inf(self, returns: np.ndarray) -> None:
        """LedoitWolfEstimator raises ValueError with 'Inf' for Inf inputs."""
        estimator = LedoitWolfEstimator()
        with pytest.raises(ValueError, match="Inf"):
            estimator.estimate(returns, DEFAULT_CONFIG)

    @given(returns=st_returns_with_inf())
    @settings(max_examples=100, deadline=None)
    def test_factor_model_estimator_rejects_inf(self, returns: np.ndarray) -> None:
        """FactorModelEstimator raises ValueError with 'Inf' for Inf inputs."""
        n = returns.shape[1]
        estimator = _make_factor_model_estimator(n)
        with pytest.raises(ValueError, match="Inf"):
            estimator.estimate(returns, DEFAULT_CONFIG)


class TestCovarianceInsufficientObservations:
    """For ANY return matrix where T < n+1, ALL estimators raise ValueError.

    **Validates: Requirements 1.6, 1.7**
    """

    @given(returns=st_returns_insufficient_obs())
    @settings(max_examples=100, deadline=None)
    def test_sample_estimator_rejects_insufficient_obs(
        self, returns: np.ndarray
    ) -> None:
        """SampleCovarianceEstimator raises ValueError with 'Insufficient observations'."""
        estimator = SampleCovarianceEstimator()
        with pytest.raises(ValueError, match="Insufficient observations"):
            estimator.estimate(returns, DEFAULT_CONFIG)

    @given(returns=st_returns_insufficient_obs())
    @settings(max_examples=100, deadline=None)
    def test_ledoit_wolf_estimator_rejects_insufficient_obs(
        self, returns: np.ndarray
    ) -> None:
        """LedoitWolfEstimator raises ValueError with 'Insufficient observations'."""
        estimator = LedoitWolfEstimator()
        with pytest.raises(ValueError, match="Insufficient observations"):
            estimator.estimate(returns, DEFAULT_CONFIG)

    @given(returns=st_returns_insufficient_obs())
    @settings(max_examples=100, deadline=None)
    def test_factor_model_estimator_rejects_insufficient_obs(
        self, returns: np.ndarray
    ) -> None:
        """FactorModelEstimator raises ValueError with 'Insufficient observations'."""
        n = returns.shape[1]
        estimator = _make_factor_model_estimator(n)
        with pytest.raises(ValueError, match="Insufficient observations"):
            estimator.estimate(returns, DEFAULT_CONFIG)


class TestCovarianceNon2DValidation:
    """For ANY non-2D array, ALL estimators raise ValueError.

    **Validates: Requirements 1.6, 1.7**
    """

    @given(array=st_non_2d_array())
    @settings(max_examples=100, deadline=None)
    def test_sample_estimator_rejects_non_2d(self, array: np.ndarray) -> None:
        """SampleCovarianceEstimator raises ValueError with '2-D' for non-2D inputs."""
        estimator = SampleCovarianceEstimator()
        with pytest.raises(ValueError, match="2-D"):
            estimator.estimate(array, DEFAULT_CONFIG)

    @given(array=st_non_2d_array())
    @settings(max_examples=100, deadline=None)
    def test_ledoit_wolf_estimator_rejects_non_2d(self, array: np.ndarray) -> None:
        """LedoitWolfEstimator raises ValueError with '2-D' for non-2D inputs."""
        estimator = LedoitWolfEstimator()
        with pytest.raises(ValueError, match="2-D"):
            estimator.estimate(array, DEFAULT_CONFIG)

    @given(array=st_non_2d_array())
    @settings(max_examples=100, deadline=None)
    def test_factor_model_estimator_rejects_non_2d(self, array: np.ndarray) -> None:
        """FactorModelEstimator raises ValueError with '2-D' for non-2D inputs.

        Note: For FactorModelEstimator, we use a fixed n=5 factor model since
        the non-2D input will be rejected before dimension consistency checks.
        """
        estimator = _make_factor_model_estimator(n=5)
        with pytest.raises(ValueError, match="2-D"):
            estimator.estimate(array, DEFAULT_CONFIG)
