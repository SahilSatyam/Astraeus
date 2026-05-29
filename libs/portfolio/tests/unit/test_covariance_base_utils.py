"""Unit tests for CovarianceEstimator ABC and covariance utility functions."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from astraeus_portfolio.contracts import CovarianceConfig, CovarianceResult
from astraeus_portfolio.covariance.base import CovarianceEstimator
from astraeus_portfolio.covariance.utils import nearest_psd, validate_returns


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class DummyEstimator(CovarianceEstimator):
    """Concrete estimator for testing the ABC interface."""

    def estimate(
        self, returns: np.ndarray, config: CovarianceConfig
    ) -> CovarianceResult:
        validate_returns(returns)
        t, n = returns.shape
        cov = np.cov(returns, rowvar=False)
        cov_psd = nearest_psd(cov, floor=config.eigenvalue_floor)
        return CovarianceResult(
            matrix=cov_psd,
            estimator="dummy",
            n_assets=n,
            n_observations=t,
            condition_number=float(
                np.linalg.cond(cov_psd)
            ),
            shrinkage_intensity=None,
            as_of_ts=datetime.now(tz=timezone.utc),
        )


# ---------------------------------------------------------------------------
# Tests: CovarianceEstimator ABC
# ---------------------------------------------------------------------------


class TestCovarianceEstimatorABC:
    """Tests for the abstract base class contract."""

    def test_cannot_instantiate_abc_directly(self) -> None:
        with pytest.raises(TypeError):
            CovarianceEstimator()  # type: ignore[abstract]

    def test_concrete_estimator_can_be_instantiated(self) -> None:
        estimator = DummyEstimator()
        assert isinstance(estimator, CovarianceEstimator)

    def test_estimate_returns_covariance_result(self) -> None:
        rng = np.random.default_rng(42)
        returns = rng.standard_normal((100, 5))
        config = CovarianceConfig()
        estimator = DummyEstimator()

        result = estimator.estimate(returns, config)

        assert isinstance(result, CovarianceResult)
        assert result.matrix.shape == (5, 5)
        assert result.n_assets == 5
        assert result.n_observations == 100
        assert result.estimator == "dummy"


# ---------------------------------------------------------------------------
# Tests: nearest_psd
# ---------------------------------------------------------------------------


class TestNearestPSD:
    """Tests for the nearest_psd eigenvalue correction function."""

    def test_already_psd_matrix_unchanged(self) -> None:
        """A PSD matrix with eigenvalues above floor should be ~unchanged."""
        matrix = np.array([[2.0, 0.5], [0.5, 1.0]])
        result = nearest_psd(matrix, floor=1e-8)

        np.testing.assert_allclose(result, matrix, atol=1e-12)

    def test_negative_eigenvalue_corrected(self) -> None:
        """A matrix with a negative eigenvalue should be corrected to PSD."""
        # Construct a matrix with a negative eigenvalue
        eigvals = np.array([2.0, -0.5])
        v = np.array([[0.6, -0.8], [0.8, 0.6]])
        matrix = v @ np.diag(eigvals) @ v.T

        result = nearest_psd(matrix, floor=1e-8)

        # All eigenvalues should be >= floor
        eigenvalues = np.linalg.eigvalsh(result)
        assert np.all(eigenvalues >= 1e-8 - 1e-12)

    def test_result_is_symmetric(self) -> None:
        """Output should always be symmetric."""
        rng = np.random.default_rng(123)
        matrix = rng.standard_normal((5, 5))
        matrix = matrix + matrix.T  # make symmetric but not necessarily PSD

        result = nearest_psd(matrix, floor=1e-8)

        np.testing.assert_allclose(result, result.T, atol=1e-14)

    def test_custom_floor_applied(self) -> None:
        """Custom floor value should be respected."""
        eigvals = np.array([1.0, 1e-12])
        v = np.eye(2)
        matrix = v @ np.diag(eigvals) @ v.T

        floor = 1e-4
        result = nearest_psd(matrix, floor=floor)

        eigenvalues = np.linalg.eigvalsh(result)
        assert np.all(eigenvalues >= floor - 1e-12)

    def test_non_square_raises_value_error(self) -> None:
        matrix = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        with pytest.raises(ValueError, match="square"):
            nearest_psd(matrix)

    def test_non_2d_raises_value_error(self) -> None:
        matrix = np.array([1.0, 2.0, 3.0])
        with pytest.raises(ValueError, match="2-D"):
            nearest_psd(matrix)

    def test_identity_matrix_unchanged(self) -> None:
        matrix = np.eye(4)
        result = nearest_psd(matrix, floor=1e-8)
        np.testing.assert_allclose(result, matrix, atol=1e-12)

    def test_zero_matrix_gets_floor_eigenvalues(self) -> None:
        """A zero matrix should get all eigenvalues set to floor."""
        matrix = np.zeros((3, 3))
        floor = 1e-8
        result = nearest_psd(matrix, floor=floor)

        eigenvalues = np.linalg.eigvalsh(result)
        np.testing.assert_allclose(eigenvalues, floor, atol=1e-14)


# ---------------------------------------------------------------------------
# Tests: validate_returns
# ---------------------------------------------------------------------------


class TestValidateReturns:
    """Tests for the validate_returns input validation function."""

    def test_valid_returns_pass(self) -> None:
        """Valid returns (T >= n+1, no NaN/Inf) should not raise."""
        rng = np.random.default_rng(42)
        returns = rng.standard_normal((10, 5))  # T=10, n=5, T >= n+1
        validate_returns(returns)  # Should not raise

    def test_nan_raises_value_error(self) -> None:
        returns = np.array([[1.0, 2.0], [3.0, np.nan], [5.0, 6.0]])
        with pytest.raises(ValueError, match="NaN"):
            validate_returns(returns)

    def test_inf_raises_value_error(self) -> None:
        returns = np.array([[1.0, 2.0], [3.0, np.inf], [5.0, 6.0]])
        with pytest.raises(ValueError, match="Inf"):
            validate_returns(returns)

    def test_negative_inf_raises_value_error(self) -> None:
        returns = np.array([[1.0, 2.0], [3.0, -np.inf], [5.0, 6.0]])
        with pytest.raises(ValueError, match="Inf"):
            validate_returns(returns)

    def test_insufficient_observations_raises(self) -> None:
        """T < n+1 should raise ValueError."""
        returns = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])  # T=2, n=3
        with pytest.raises(ValueError, match="Insufficient observations"):
            validate_returns(returns)

    def test_exact_minimum_observations_pass(self) -> None:
        """T = n+1 should pass (boundary case)."""
        rng = np.random.default_rng(42)
        n = 4
        returns = rng.standard_normal((n + 1, n))  # T=5, n=4
        validate_returns(returns)  # Should not raise

    def test_1d_array_raises(self) -> None:
        returns = np.array([1.0, 2.0, 3.0])
        with pytest.raises(ValueError, match="2-D"):
            validate_returns(returns)

    def test_3d_array_raises(self) -> None:
        returns = np.ones((3, 3, 3))
        with pytest.raises(ValueError, match="2-D"):
            validate_returns(returns)

    def test_single_asset_valid(self) -> None:
        """Single asset with T >= 2 should pass."""
        returns = np.array([[0.01], [0.02]])  # T=2, n=1, T >= n+1=2
        validate_returns(returns)  # Should not raise

    def test_error_message_includes_dimensions(self) -> None:
        """Error message should include T and n values."""
        returns = np.array([[1.0, 2.0, 3.0, 4.0]])  # T=1, n=4
        with pytest.raises(ValueError, match=r"T=1.*n=4"):
            validate_returns(returns)
