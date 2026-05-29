"""Unit tests for the SampleCovarianceEstimator."""

from __future__ import annotations

import numpy as np
import pytest
from astraeus_portfolio.contracts import CovarianceConfig, CovarianceResult
from astraeus_portfolio.covariance.sample import SampleCovarianceEstimator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def estimator() -> SampleCovarianceEstimator:
    return SampleCovarianceEstimator()


@pytest.fixture
def config() -> CovarianceConfig:
    return CovarianceConfig()


@pytest.fixture
def valid_returns() -> np.ndarray:
    """Generate a valid T×n return matrix (T=100, n=5)."""
    rng = np.random.default_rng(42)
    return rng.standard_normal((100, 5))


# ---------------------------------------------------------------------------
# Tests: Basic functionality
# ---------------------------------------------------------------------------


class TestSampleCovarianceEstimator:
    """Tests for SampleCovarianceEstimator.estimate()."""

    def test_returns_covariance_result(
        self,
        estimator: SampleCovarianceEstimator,
        config: CovarianceConfig,
        valid_returns: np.ndarray,
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert isinstance(result, CovarianceResult)

    def test_estimator_field_is_sample(
        self,
        estimator: SampleCovarianceEstimator,
        config: CovarianceConfig,
        valid_returns: np.ndarray,
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.estimator == "sample"

    def test_shrinkage_intensity_is_none(
        self,
        estimator: SampleCovarianceEstimator,
        config: CovarianceConfig,
        valid_returns: np.ndarray,
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.shrinkage_intensity is None

    def test_matrix_shape_matches_assets(
        self,
        estimator: SampleCovarianceEstimator,
        config: CovarianceConfig,
        valid_returns: np.ndarray,
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        n = valid_returns.shape[1]
        assert result.matrix.shape == (n, n)

    def test_n_assets_correct(
        self,
        estimator: SampleCovarianceEstimator,
        config: CovarianceConfig,
        valid_returns: np.ndarray,
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.n_assets == valid_returns.shape[1]

    def test_n_observations_correct(
        self,
        estimator: SampleCovarianceEstimator,
        config: CovarianceConfig,
        valid_returns: np.ndarray,
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.n_observations == valid_returns.shape[0]

    def test_matrix_is_symmetric(
        self,
        estimator: SampleCovarianceEstimator,
        config: CovarianceConfig,
        valid_returns: np.ndarray,
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        np.testing.assert_allclose(result.matrix, result.matrix.T, atol=1e-14)

    def test_matrix_is_psd(
        self,
        estimator: SampleCovarianceEstimator,
        config: CovarianceConfig,
        valid_returns: np.ndarray,
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        eigenvalues = np.linalg.eigvalsh(result.matrix)
        assert np.all(eigenvalues >= config.eigenvalue_floor - 1e-12)

    def test_condition_number_positive(
        self,
        estimator: SampleCovarianceEstimator,
        config: CovarianceConfig,
        valid_returns: np.ndarray,
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.condition_number > 0

    def test_as_of_ts_is_set(
        self,
        estimator: SampleCovarianceEstimator,
        config: CovarianceConfig,
        valid_returns: np.ndarray,
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.as_of_ts is not None


# ---------------------------------------------------------------------------
# Tests: Input validation delegation
# ---------------------------------------------------------------------------


class TestSampleCovarianceValidation:
    """Tests that SampleCovarianceEstimator delegates to validate_returns."""

    def test_nan_raises_value_error(
        self, estimator: SampleCovarianceEstimator, config: CovarianceConfig
    ) -> None:
        returns = np.array([[1.0, 2.0], [3.0, np.nan], [5.0, 6.0]])
        with pytest.raises(ValueError, match="NaN"):
            estimator.estimate(returns, config)

    def test_inf_raises_value_error(
        self, estimator: SampleCovarianceEstimator, config: CovarianceConfig
    ) -> None:
        returns = np.array([[1.0, 2.0], [3.0, np.inf], [5.0, 6.0]])
        with pytest.raises(ValueError, match="Inf"):
            estimator.estimate(returns, config)

    def test_insufficient_observations_raises(
        self, estimator: SampleCovarianceEstimator, config: CovarianceConfig
    ) -> None:
        # T=2, n=3 -> T < n+1
        returns = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        with pytest.raises(ValueError, match="Insufficient observations"):
            estimator.estimate(returns, config)

    def test_1d_array_raises(
        self, estimator: SampleCovarianceEstimator, config: CovarianceConfig
    ) -> None:
        returns = np.array([1.0, 2.0, 3.0])
        with pytest.raises(ValueError, match="2-D"):
            estimator.estimate(returns, config)


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------


class TestSampleCovarianceEdgeCases:
    """Tests for boundary conditions and edge cases."""

    def test_minimum_observations(
        self, estimator: SampleCovarianceEstimator, config: CovarianceConfig
    ) -> None:
        """T = n+1 (minimum valid) should succeed."""
        rng = np.random.default_rng(42)
        n = 4
        returns = rng.standard_normal((n + 1, n))
        result = estimator.estimate(returns, config)
        assert result.matrix.shape == (n, n)

    def test_single_asset(
        self, estimator: SampleCovarianceEstimator, config: CovarianceConfig
    ) -> None:
        """Single asset (n=1) with T >= 2 should produce a 1×1 matrix."""
        returns = np.array([[0.01], [0.02], [-0.01], [0.03]])
        result = estimator.estimate(returns, config)
        assert result.matrix.shape == (1, 1)
        assert result.n_assets == 1

    def test_known_covariance(self, estimator: SampleCovarianceEstimator) -> None:
        """Verify against a known covariance for a simple case."""
        # Two perfectly correlated assets
        returns = np.array(
            [
                [0.01, 0.02],
                [0.02, 0.04],
                [-0.01, -0.02],
            ]
        )
        config = CovarianceConfig(eigenvalue_floor=1e-10)
        result = estimator.estimate(returns, config)

        # np.cov with ddof=1 for these returns
        expected = np.cov(returns, rowvar=False)
        # After nearest_psd, should be close (already PSD in this case)
        np.testing.assert_allclose(result.matrix, expected, atol=1e-9)

    def test_eigenvalue_floor_applied(self, estimator: SampleCovarianceEstimator) -> None:
        """Verify that eigenvalue floor is applied from config."""
        # Create returns that produce a near-singular covariance
        # (two nearly identical columns)
        rng = np.random.default_rng(99)
        base = rng.standard_normal((50, 1))
        noise = rng.standard_normal((50, 1)) * 1e-15
        returns = np.hstack([base, base + noise, rng.standard_normal((50, 1))])

        floor = 1e-6
        config = CovarianceConfig(eigenvalue_floor=floor)
        result = estimator.estimate(returns, config)

        eigenvalues = np.linalg.eigvalsh(result.matrix)
        assert np.all(eigenvalues >= floor - 1e-12)
