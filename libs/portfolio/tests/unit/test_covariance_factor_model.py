"""Unit tests for the FactorModelEstimator."""

from __future__ import annotations

import numpy as np
import pytest
from astraeus_portfolio.contracts import CovarianceConfig, CovarianceResult
from astraeus_portfolio.covariance.factor_model import FactorModelEstimator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> CovarianceConfig:
    return CovarianceConfig()


@pytest.fixture
def factor_model_inputs() -> dict:
    """Generate valid factor model inputs (n=5 assets, k=3 factors)."""
    rng = np.random.default_rng(42)
    n, k = 5, 3
    B = rng.standard_normal((n, k))
    # Make F positive definite
    raw = rng.standard_normal((k, k))
    F = raw @ raw.T + np.eye(k) * 0.1
    D = np.abs(rng.standard_normal(n)) * 0.01  # 1-D vector
    return {"B": B, "F": F, "D": D, "n": n, "k": k}


@pytest.fixture
def valid_returns() -> np.ndarray:
    """Generate a valid T×n return matrix (T=100, n=5)."""
    rng = np.random.default_rng(42)
    return rng.standard_normal((100, 5))


@pytest.fixture
def estimator(factor_model_inputs: dict) -> FactorModelEstimator:
    return FactorModelEstimator(
        factor_loadings=factor_model_inputs["B"],
        factor_covariance=factor_model_inputs["F"],
        idiosyncratic_variance=factor_model_inputs["D"],
    )


# ---------------------------------------------------------------------------
# Tests: Basic functionality
# ---------------------------------------------------------------------------


class TestFactorModelEstimator:
    """Tests for FactorModelEstimator.estimate()."""

    def test_returns_covariance_result(
        self, estimator: FactorModelEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert isinstance(result, CovarianceResult)

    def test_estimator_field_is_factor_model(
        self, estimator: FactorModelEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.estimator == "factor_model"

    def test_shrinkage_intensity_is_none(
        self, estimator: FactorModelEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.shrinkage_intensity is None

    def test_matrix_shape_matches_assets(
        self, estimator: FactorModelEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        n = valid_returns.shape[1]
        assert result.matrix.shape == (n, n)

    def test_n_assets_correct(
        self, estimator: FactorModelEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.n_assets == valid_returns.shape[1]

    def test_n_observations_correct(
        self, estimator: FactorModelEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.n_observations == valid_returns.shape[0]

    def test_matrix_is_symmetric(
        self, estimator: FactorModelEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        np.testing.assert_allclose(result.matrix, result.matrix.T, atol=1e-14)

    def test_matrix_is_psd(
        self, estimator: FactorModelEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        eigenvalues = np.linalg.eigvalsh(result.matrix)
        assert np.all(eigenvalues >= config.eigenvalue_floor - 1e-12)

    def test_condition_number_positive(
        self, estimator: FactorModelEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.condition_number > 0

    def test_as_of_ts_is_set(
        self, estimator: FactorModelEstimator, config: CovarianceConfig, valid_returns: np.ndarray
    ) -> None:
        result = estimator.estimate(valid_returns, config)
        assert result.as_of_ts is not None

    def test_known_factor_model_covariance(self) -> None:
        """Verify B @ F @ B' + D produces the expected result."""
        # Simple 2-asset, 1-factor model
        B = np.array([[1.0], [0.5]])  # 2×1
        F = np.array([[0.04]])  # 1×1 (factor variance = 4%)
        D = np.array([0.01, 0.02])  # idiosyncratic variances

        estimator = FactorModelEstimator(
            factor_loadings=B,
            factor_covariance=F,
            idiosyncratic_variance=D,
        )

        # Need valid returns: T >= n+1 = 3, n=2
        rng = np.random.default_rng(123)
        returns = rng.standard_normal((10, 2))

        config = CovarianceConfig(eigenvalue_floor=1e-10)
        result = estimator.estimate(returns, config)

        # Expected: B @ F @ B' + diag(D)
        expected = B @ F @ B.T + np.diag(D)
        # After nearest_psd (already PSD), should be very close
        np.testing.assert_allclose(result.matrix, expected, atol=1e-8)


# ---------------------------------------------------------------------------
# Tests: Idiosyncratic variance as 2-D diagonal matrix
# ---------------------------------------------------------------------------


class TestFactorModelDiagonalMatrix:
    """Tests for accepting D as a 2-D diagonal matrix."""

    def test_2d_diagonal_matrix_accepted(self, valid_returns: np.ndarray) -> None:
        rng = np.random.default_rng(42)
        n, k = 5, 3
        B = rng.standard_normal((n, k))
        raw = rng.standard_normal((k, k))
        F = raw @ raw.T + np.eye(k) * 0.1
        D_vec = np.abs(rng.standard_normal(n)) * 0.01
        D_mat = np.diag(D_vec)

        est_vec = FactorModelEstimator(B, F, D_vec)
        est_mat = FactorModelEstimator(B, F, D_mat)

        config = CovarianceConfig()
        result_vec = est_vec.estimate(valid_returns, config)
        result_mat = est_mat.estimate(valid_returns, config)

        np.testing.assert_allclose(result_vec.matrix, result_mat.matrix, atol=1e-14)


# ---------------------------------------------------------------------------
# Tests: Input validation
# ---------------------------------------------------------------------------


class TestFactorModelValidation:
    """Tests that FactorModelEstimator validates inputs correctly."""

    def test_nan_in_returns_raises(
        self, estimator: FactorModelEstimator, config: CovarianceConfig
    ) -> None:
        returns = np.array(
            [[1.0, 2.0, 3.0, 4.0, 5.0], [3.0, np.nan, 5.0, 6.0, 7.0], [5.0, 6.0, 7.0, 8.0, 9.0]]
        )
        with pytest.raises(ValueError, match="NaN"):
            estimator.estimate(returns, config)

    def test_inf_in_returns_raises(
        self, estimator: FactorModelEstimator, config: CovarianceConfig
    ) -> None:
        returns = np.array(
            [[1.0, 2.0, 3.0, 4.0, 5.0], [3.0, np.inf, 5.0, 6.0, 7.0], [5.0, 6.0, 7.0, 8.0, 9.0]]
        )
        with pytest.raises(ValueError, match="Inf"):
            estimator.estimate(returns, config)

    def test_insufficient_observations_raises(
        self, estimator: FactorModelEstimator, config: CovarianceConfig
    ) -> None:
        # T=2, n=5 -> T < n+1
        returns = np.ones((2, 5))
        with pytest.raises(ValueError, match="Insufficient observations"):
            estimator.estimate(returns, config)

    def test_dimension_mismatch_raises(self, config: CovarianceConfig) -> None:
        """Returns with n=3 but B has n=5 rows should raise."""
        rng = np.random.default_rng(42)
        B = rng.standard_normal((5, 3))
        F = np.eye(3)
        D = np.ones(5) * 0.01

        estimator = FactorModelEstimator(B, F, D)
        returns = rng.standard_normal((100, 3))  # n=3, but B expects n=5
        with pytest.raises(ValueError, match="Dimensions must match"):
            estimator.estimate(returns, config)

    def test_1d_returns_raises(
        self, estimator: FactorModelEstimator, config: CovarianceConfig
    ) -> None:
        returns = np.array([1.0, 2.0, 3.0])
        with pytest.raises(ValueError, match="2-D"):
            estimator.estimate(returns, config)


# ---------------------------------------------------------------------------
# Tests: Constructor validation
# ---------------------------------------------------------------------------


class TestFactorModelConstructorValidation:
    """Tests for constructor input validation."""

    def test_1d_factor_loadings_raises(self) -> None:
        with pytest.raises(ValueError, match="2-D"):
            FactorModelEstimator(
                factor_loadings=np.array([1.0, 2.0, 3.0]),
                factor_covariance=np.eye(1),
                idiosyncratic_variance=np.array([0.01, 0.01, 0.01]),
            )

    def test_factor_covariance_shape_mismatch_raises(self) -> None:
        B = np.ones((5, 3))
        with pytest.raises(ValueError, match="Factor covariance matrix must be"):
            FactorModelEstimator(
                factor_loadings=B,
                factor_covariance=np.eye(2),  # Should be 3×3
                idiosyncratic_variance=np.ones(5) * 0.01,
            )

    def test_idiosyncratic_variance_length_mismatch_raises(self) -> None:
        B = np.ones((5, 3))
        F = np.eye(3)
        with pytest.raises(ValueError, match="Idiosyncratic variance vector must have"):
            FactorModelEstimator(
                factor_loadings=B,
                factor_covariance=F,
                idiosyncratic_variance=np.ones(4) * 0.01,  # Should be 5
            )

    def test_negative_idiosyncratic_variance_raises(self) -> None:
        B = np.ones((5, 3))
        F = np.eye(3)
        with pytest.raises(ValueError, match="non-negative"):
            FactorModelEstimator(
                factor_loadings=B,
                factor_covariance=F,
                idiosyncratic_variance=np.array([0.01, -0.01, 0.01, 0.01, 0.01]),
            )

    def test_3d_idiosyncratic_variance_raises(self) -> None:
        B = np.ones((5, 3))
        F = np.eye(3)
        with pytest.raises(ValueError, match="1-D.*or 2-D"):
            FactorModelEstimator(
                factor_loadings=B,
                factor_covariance=F,
                idiosyncratic_variance=np.ones((5, 5, 5)) * 0.01,
            )

    def test_2d_idiosyncratic_wrong_shape_raises(self) -> None:
        B = np.ones((5, 3))
        F = np.eye(3)
        with pytest.raises(ValueError, match="Idiosyncratic variance matrix must be"):
            FactorModelEstimator(
                factor_loadings=B,
                factor_covariance=F,
                idiosyncratic_variance=np.eye(4) * 0.01,  # Should be 5×5
            )
