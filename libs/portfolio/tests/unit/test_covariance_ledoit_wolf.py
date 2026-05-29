"""Unit tests for the LedoitWolfEstimator."""

from __future__ import annotations

import numpy as np
import pytest
from astraeus_portfolio.contracts import CovarianceConfig, CovarianceResult
from astraeus_portfolio.covariance.ledoit_wolf import LedoitWolfEstimator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def estimator() -> LedoitWolfEstimator:
    return LedoitWolfEstimator()


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


class TestLedoitWolfEstimator:
    """Tests for LedoitWolfEstimator.estimate()."""

    def test_returns_covariance_result(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert isinstance(result, CovarianceResult)

    def test_estimator_field_is_ledoit_wolf(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.estimator == "ledoit_wolf"

    def test_shrinkage_intensity_is_set(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.shrinkage_intensity is not None
        assert 0.0 <= result.shrinkage_intensity <= 1.0

    def test_matrix_shape_matches_assets(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        n = valid_returns.shape[1]
        assert result.matrix.shape == (n, n)

    def test_n_assets_correct(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.n_assets == valid_returns.shape[1]

    def test_n_observations_correct(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.n_observations == valid_returns.shape[0]

    def test_matrix_is_symmetric(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        np.testing.assert_allclose(result.matrix, result.matrix.T, atol=1e-14)

    def test_matrix_is_psd(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        eigenvalues = np.linalg.eigvalsh(result.matrix)
        assert np.all(eigenvalues >= config.eigenvalue_floor - 1e-12)

    def test_condition_number_positive(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.condition_number > 0

    def test_as_of_ts_is_set(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.as_of_ts is not None


# ---------------------------------------------------------------------------
# Tests: Shrinkage behavior
# ---------------------------------------------------------------------------


class TestLedoitWolfShrinkage:
    """Tests for shrinkage-specific behavior."""

    def test_shrinkage_reduces_condition_number(self, estimator: LedoitWolfEstimator) -> None:
        """Shrinkage toward identity should reduce condition number vs sample."""
        rng = np.random.default_rng(123)
        # Create returns with high condition number (correlated assets)
        base = rng.standard_normal((200, 3))
        returns = np.column_stack([base, base[:, 0:1] + rng.standard_normal((200, 1)) * 0.01])

        config = CovarianceConfig(eigenvalue_floor=1e-10)
        result = estimator.estimate(returns, config)

        # Sample covariance condition number
        sample_cov = np.cov(returns, rowvar=False)
        sample_cond = float(np.linalg.cond(sample_cov))

        # Shrunk matrix should have lower or equal condition number
        assert result.condition_number <= sample_cond + 1e-6

    def test_shrinkage_intensity_between_zero_and_one(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig
    ) -> None:
        """Shrinkage intensity must be in [0, 1]."""
        rng = np.random.default_rng(77)
        returns = rng.standard_normal((50, 10))
        result = estimator.estimate(returns, config)
        assert 0.0 <= result.shrinkage_intensity <= 1.0

    def test_more_observations_less_shrinkage(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig
    ) -> None:
        """With more observations from the same DGP, shrinkage should decrease."""
        n = 5
        # Use correlated returns so the target differs from sample cov
        # Same DGP (same seed, same correlation structure) but different T
        cov_true = np.array(
            [
                [1.0, 0.5, 0.3, 0.2, 0.1],
                [0.5, 1.0, 0.4, 0.3, 0.2],
                [0.3, 0.4, 1.0, 0.5, 0.3],
                [0.2, 0.3, 0.5, 1.0, 0.4],
                [0.1, 0.2, 0.3, 0.4, 1.0],
            ]
        )
        L = np.linalg.cholesky(cov_true)

        rng_small = np.random.default_rng(55)
        z_small = rng_small.standard_normal((20, n))
        returns_small = z_small @ L.T

        rng_large = np.random.default_rng(55)
        z_large = rng_large.standard_normal((2000, n))
        returns_large = z_large @ L.T

        result_small = estimator.estimate(returns_small, config)
        result_large = estimator.estimate(returns_large, config)

        # With more observations, estimation error decreases -> less shrinkage
        assert result_small.shrinkage_intensity > result_large.shrinkage_intensity

    def test_correlated_assets_nonzero_shrinkage(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig
    ) -> None:
        """Correlated assets with moderate T should produce nonzero shrinkage."""
        rng = np.random.default_rng(88)
        # Create correlated returns where sample cov differs from identity
        n = 10
        base = rng.standard_normal((60, 3))
        noise = rng.standard_normal((60, n)) * 0.3
        returns = noise + base[:, : min(3, n)] @ rng.standard_normal((3, n))
        result = estimator.estimate(returns, config)
        # Should have some shrinkage (not zero)
        assert result.shrinkage_intensity > 0.0


# ---------------------------------------------------------------------------
# Tests: Input validation delegation
# ---------------------------------------------------------------------------


class TestLedoitWolfValidation:
    """Tests that LedoitWolfEstimator delegates to validate_returns."""

    def test_nan_raises_value_error(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig
    ) -> None:
        returns = np.array([[1.0, 2.0], [3.0, np.nan], [5.0, 6.0]])
        with pytest.raises(ValueError, match="NaN"):
            estimator.estimate(returns, config)

    def test_inf_raises_value_error(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig
    ) -> None:
        returns = np.array([[1.0, 2.0], [3.0, np.inf], [5.0, 6.0]])
        with pytest.raises(ValueError, match="Inf"):
            estimator.estimate(returns, config)

    def test_insufficient_observations_raises(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig
    ) -> None:
        # T=2, n=3 -> T < n+1
        returns = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        with pytest.raises(ValueError, match="Insufficient observations"):
            estimator.estimate(returns, config)

    def test_1d_array_raises(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig
    ) -> None:
        returns = np.array([1.0, 2.0, 3.0])
        with pytest.raises(ValueError, match="2-D"):
            estimator.estimate(returns, config)


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------


class TestLedoitWolfEdgeCases:
    """Tests for boundary conditions and edge cases."""

    def test_minimum_observations(
        self, estimator: LedoitWolfEstimator, config: CovarianceConfig
    ) -> None:
        """T = n+1 (minimum valid) should succeed."""
        rng = np.random.default_rng(42)
        n = 4
        returns = rng.standard_normal((n + 1, n))
        result = estimator.estimate(returns, config)
        assert result.matrix.shape == (n, n)

    def test_single_asset(self, estimator: LedoitWolfEstimator, config: CovarianceConfig) -> None:
        """Single asset (n=1) with T >= 2 should produce a 1×1 matrix."""
        returns = np.array([[0.01], [0.02], [-0.01], [0.03]])
        result = estimator.estimate(returns, config)
        assert result.matrix.shape == (1, 1)
        assert result.n_assets == 1

    def test_eigenvalue_floor_applied(self, estimator: LedoitWolfEstimator) -> None:
        """Verify that eigenvalue floor is applied from config."""
        rng = np.random.default_rng(99)
        base = rng.standard_normal((50, 1))
        noise = rng.standard_normal((50, 1)) * 1e-15
        returns = np.hstack([base, base + noise, rng.standard_normal((50, 1))])

        floor = 1e-6
        config = CovarianceConfig(eigenvalue_floor=floor)
        result = estimator.estimate(returns, config)

        eigenvalues = np.linalg.eigvalsh(result.matrix)
        assert np.all(eigenvalues >= floor - 1e-12)

    def test_large_universe(self, estimator: LedoitWolfEstimator, config: CovarianceConfig) -> None:
        """Test with a larger universe (n=50, T=100)."""
        rng = np.random.default_rng(101)
        returns = rng.standard_normal((100, 50))
        result = estimator.estimate(returns, config)
        assert result.matrix.shape == (50, 50)
        assert result.shrinkage_intensity is not None
