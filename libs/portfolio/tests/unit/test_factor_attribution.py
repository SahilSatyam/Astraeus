"""Unit tests for factor-model PnL attribution (FF5+MOM)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import pytest

from astraeus_portfolio.attribution.factor_model import (
    FACTOR_NAMES,
    FactorAttributionEngine,
    FactorDataUnavailableError,
    RegressionResult,
    _newey_west_se,
    _run_ols_regression,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(42)


@pytest.fixture
def engine() -> FactorAttributionEngine:
    return FactorAttributionEngine()


@pytest.fixture
def portfolio_id():
    return uuid4()


@pytest.fixture
def as_of_ts():
    return datetime(2024, 1, 15, 16, 30, 0)


@pytest.fixture
def simple_factor_returns(rng: np.random.Generator) -> np.ndarray:
    """Generate 253 days of factor returns (252 history + 1 realized)."""
    return rng.standard_normal((253, 6)) * 0.01


@pytest.fixture
def simple_weights() -> np.ndarray:
    """Equal-weight portfolio of 5 assets."""
    return np.array([0.2, 0.2, 0.2, 0.2, 0.2])


@pytest.fixture
def simple_realized_returns(rng: np.random.Generator) -> np.ndarray:
    """Realized returns for 5 assets."""
    return rng.standard_normal(5) * 0.01


# ---------------------------------------------------------------------------
# Tests: Input Validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Tests for input validation in run_factor_attribution."""

    def test_weights_must_be_1d(self, engine, portfolio_id, as_of_ts, simple_factor_returns):
        weights = np.ones((3, 3))
        realized = np.ones(3)
        with pytest.raises(ValueError, match="weights must be 1-D"):
            engine.run_factor_attribution(
                portfolio_id, as_of_ts, weights, realized, simple_factor_returns
            )

    def test_realized_returns_must_be_1d(
        self, engine, portfolio_id, as_of_ts, simple_factor_returns
    ):
        weights = np.ones(3)
        realized = np.ones((3, 2))
        with pytest.raises(ValueError, match="realized_returns must be 1-D"):
            engine.run_factor_attribution(
                portfolio_id, as_of_ts, weights, realized, simple_factor_returns
            )

    def test_weights_and_returns_length_mismatch(
        self, engine, portfolio_id, as_of_ts, simple_factor_returns
    ):
        weights = np.ones(3)
        realized = np.ones(5)
        with pytest.raises(ValueError, match="must have same length"):
            engine.run_factor_attribution(
                portfolio_id, as_of_ts, weights, realized, simple_factor_returns
            )

    def test_factor_returns_must_be_2d(self, engine, portfolio_id, as_of_ts):
        weights = np.ones(3)
        realized = np.ones(3)
        factor_returns = np.ones(6)
        with pytest.raises(ValueError, match="factor_returns must be 2-D"):
            engine.run_factor_attribution(
                portfolio_id, as_of_ts, weights, realized, factor_returns
            )

    def test_factor_returns_must_have_6_columns(self, engine, portfolio_id, as_of_ts):
        weights = np.ones(3)
        realized = np.ones(3)
        factor_returns = np.ones((100, 4))
        with pytest.raises(ValueError, match="must have 6 columns"):
            engine.run_factor_attribution(
                portfolio_id, as_of_ts, weights, realized, factor_returns
            )

    def test_factor_returns_must_have_at_least_2_rows(
        self, engine, portfolio_id, as_of_ts
    ):
        weights = np.ones(3)
        realized = np.ones(3)
        factor_returns = np.ones((1, 6))
        with pytest.raises(ValueError, match="at least 2 rows"):
            engine.run_factor_attribution(
                portfolio_id, as_of_ts, weights, realized, factor_returns
            )

    def test_nan_in_factor_returns_rejected(self, engine, portfolio_id, as_of_ts):
        weights = np.ones(3)
        realized = np.ones(3)
        factor_returns = np.ones((100, 6))
        factor_returns[50, 2] = np.nan
        with pytest.raises(ValueError, match="NaN or Inf"):
            engine.run_factor_attribution(
                portfolio_id, as_of_ts, weights, realized, factor_returns
            )

    def test_inf_in_weights_rejected(self, engine, portfolio_id, as_of_ts):
        weights = np.array([0.5, np.inf, 0.5])
        realized = np.ones(3)
        factor_returns = np.ones((100, 6))
        with pytest.raises(ValueError, match="weights contains NaN or Inf"):
            engine.run_factor_attribution(
                portfolio_id, as_of_ts, weights, realized, factor_returns
            )


# ---------------------------------------------------------------------------
# Tests: OLS Regression
# ---------------------------------------------------------------------------


class TestOLSRegression:
    """Tests for the OLS regression function."""

    def test_perfect_linear_relationship(self):
        """When asset returns are a perfect linear combination of factors, betas are exact."""
        rng = np.random.default_rng(123)
        T = 200
        factor_returns = rng.standard_normal((T, 6)) * 0.01
        true_betas = np.array([1.2, 0.5, -0.3, 0.8, -0.1, 0.4])
        true_alpha = 0.0001

        asset_returns = true_alpha + factor_returns @ true_betas

        result = _run_ols_regression(asset_returns, factor_returns)

        np.testing.assert_allclose(result.betas, true_betas, atol=1e-10)
        assert abs(result.alpha - true_alpha) < 1e-10
        assert result.n_obs == T

    def test_noisy_regression_reasonable_betas(self):
        """With noise, betas should be close to true values."""
        rng = np.random.default_rng(456)
        T = 252
        factor_returns = rng.standard_normal((T, 6)) * 0.01
        true_betas = np.array([1.0, 0.3, -0.2, 0.5, 0.1, -0.3])
        noise = rng.standard_normal(T) * 0.005

        asset_returns = factor_returns @ true_betas + noise

        result = _run_ols_regression(asset_returns, factor_returns)

        # With noise, betas should be within reasonable tolerance
        np.testing.assert_allclose(result.betas, true_betas, atol=0.15)
        assert result.n_obs == T
        assert result.residual_std > 0

    def test_newey_west_se_positive(self):
        """Newey-West standard errors should be positive."""
        rng = np.random.default_rng(789)
        T = 200
        factor_returns = rng.standard_normal((T, 6)) * 0.01
        asset_returns = rng.standard_normal(T) * 0.01

        result = _run_ols_regression(asset_returns, factor_returns)

        assert all(se > 0 for se in result.nw_std_errors)
        assert len(result.nw_std_errors) == 7  # alpha + 6 betas


# ---------------------------------------------------------------------------
# Tests: Newey-West HAC Standard Errors
# ---------------------------------------------------------------------------


class TestNeweyWestSE:
    """Tests for Newey-West HAC standard error computation."""

    def test_se_with_no_autocorrelation(self):
        """With iid errors, NW SE should be close to classical OLS SE."""
        rng = np.random.default_rng(101)
        T = 500
        X = np.column_stack([np.ones(T), rng.standard_normal((T, 3))])
        true_beta = np.array([0.1, 0.5, -0.3, 0.8])
        errors = rng.standard_normal(T) * 0.01
        y = X @ true_beta + errors
        beta_hat = np.linalg.solve(X.T @ X, X.T @ y)
        residuals = y - X @ beta_hat

        nw_se = _newey_west_se(X, residuals, lag=5)

        # Classical SE for comparison
        s2 = np.sum(residuals**2) / (T - 4)
        classical_se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))

        # NW SE should be reasonably close to classical SE with iid errors
        np.testing.assert_allclose(nw_se, classical_se, rtol=0.3)

    def test_se_positive_definite(self):
        """Standard errors should always be positive."""
        rng = np.random.default_rng(202)
        T = 200
        X = np.column_stack([np.ones(T), rng.standard_normal((T, 6))])
        residuals = rng.standard_normal(T) * 0.01

        se = _newey_west_se(X, residuals, lag=5)

        assert all(s > 0 for s in se)


# ---------------------------------------------------------------------------
# Tests: Factor Attribution Engine
# ---------------------------------------------------------------------------


class TestFactorAttributionEngine:
    """Tests for the main attribution engine."""

    def test_basic_attribution_returns_correct_structure(
        self, engine, portfolio_id, as_of_ts, simple_weights, simple_factor_returns
    ):
        """Attribution result has correct structure and method."""
        realized = np.array([0.01, -0.005, 0.003, 0.008, -0.002])

        result = engine.run_factor_attribution(
            portfolio_id, as_of_ts, simple_weights, realized, simple_factor_returns
        )

        assert result.portfolio_id == portfolio_id
        assert result.as_of_ts == as_of_ts
        assert result.method == "factor_ff5_mom"
        assert result.factor_pnl is not None
        assert len(result.factor_pnl) == 6
        assert all(name in result.factor_pnl for name in FACTOR_NAMES)
        assert result.idio_pnl_bps is not None
        assert result.sector_pnl is None

    def test_pnl_reconciliation(
        self, engine, portfolio_id, as_of_ts, simple_weights, simple_factor_returns
    ):
        """Total PnL = sum(factor PnL) + idiosyncratic PnL."""
        realized = np.array([0.01, -0.005, 0.003, 0.008, -0.002])

        result = engine.run_factor_attribution(
            portfolio_id, as_of_ts, simple_weights, realized, simple_factor_returns
        )

        factor_sum = sum(result.factor_pnl.values())
        reconstructed = factor_sum + result.idio_pnl_bps

        # Should reconcile within 0.01 bps tolerance
        assert abs(float(result.total_pnl_bps - reconstructed)) < 0.01

    def test_zero_weights_produce_zero_pnl(
        self, engine, portfolio_id, as_of_ts, simple_factor_returns
    ):
        """Zero weights should produce zero total PnL."""
        weights = np.zeros(5)
        realized = np.array([0.01, -0.005, 0.003, 0.008, -0.002])

        result = engine.run_factor_attribution(
            portfolio_id, as_of_ts, weights, realized, simple_factor_returns
        )

        assert float(result.total_pnl_bps) == 0.0

    def test_total_pnl_matches_weighted_returns(
        self, engine, portfolio_id, as_of_ts, simple_weights, simple_factor_returns
    ):
        """Total PnL in bps should match weights @ realized_returns * 10000."""
        realized = np.array([0.01, -0.005, 0.003, 0.008, -0.002])
        expected_pnl = float(np.dot(simple_weights, realized)) * 10000

        result = engine.run_factor_attribution(
            portfolio_id, as_of_ts, simple_weights, realized, simple_factor_returns
        )

        assert abs(float(result.total_pnl_bps) - expected_pnl) < 0.01


# ---------------------------------------------------------------------------
# Tests: Full Attribution with Asset Returns
# ---------------------------------------------------------------------------


class TestFullAttribution:
    """Tests for run_full_attribution with historical asset returns."""

    def test_full_attribution_with_sufficient_history(self, engine, portfolio_id, as_of_ts):
        """Full attribution works with sufficient asset return history."""
        rng = np.random.default_rng(42)
        n_assets = 5
        T = 252

        factor_returns_history = rng.standard_normal((T, 6)) * 0.01
        true_betas = rng.standard_normal((n_assets, 6)) * 0.5
        noise = rng.standard_normal((T, n_assets)) * 0.005
        asset_returns_history = factor_returns_history @ true_betas.T + noise

        weights = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
        realized_factor = rng.standard_normal(6) * 0.01
        realized_returns = realized_factor @ true_betas.T + rng.standard_normal(n_assets) * 0.002

        result = engine.run_full_attribution(
            portfolio_id=portfolio_id,
            as_of_ts=as_of_ts,
            weights=weights,
            realized_returns=realized_returns,
            asset_returns_history=asset_returns_history,
            factor_returns_history=factor_returns_history,
            realized_factor_returns=realized_factor,
        )

        assert result.method == "factor_ff5_mom"
        assert result.factor_pnl is not None
        assert len(result.factor_pnl) == 6
        # PnL reconciliation
        factor_sum = sum(result.factor_pnl.values())
        assert abs(float(result.total_pnl_bps - factor_sum - result.idio_pnl_bps)) < 0.01

    def test_assets_below_min_history_excluded(self, engine, portfolio_id, as_of_ts):
        """Assets with < 126 days of history are excluded from regression."""
        rng = np.random.default_rng(55)
        n_assets = 3
        T = 252

        factor_returns_history = rng.standard_normal((T, 6)) * 0.01
        asset_returns_history = rng.standard_normal((T, n_assets)) * 0.01

        # Make asset 2 have only 50 valid days (rest NaN)
        asset_returns_history[:202, 2] = np.nan

        weights = np.array([0.4, 0.4, 0.2])
        realized_factor = rng.standard_normal(6) * 0.01
        realized_returns = rng.standard_normal(n_assets) * 0.01

        result = engine.run_full_attribution(
            portfolio_id=portfolio_id,
            as_of_ts=as_of_ts,
            weights=weights,
            realized_returns=realized_returns,
            asset_returns_history=asset_returns_history,
            factor_returns_history=factor_returns_history,
            realized_factor_returns=realized_factor,
        )

        # Should still produce valid result
        assert result.method == "factor_ff5_mom"
        # PnL reconciliation still holds
        factor_sum = sum(result.factor_pnl.values())
        assert abs(float(result.total_pnl_bps - factor_sum - result.idio_pnl_bps)) < 0.01

    def test_all_assets_excluded_all_goes_to_idio(self, engine, portfolio_id, as_of_ts):
        """When all assets are excluded, all PnL goes to idiosyncratic."""
        rng = np.random.default_rng(77)
        n_assets = 3
        T = 100  # Less than min_history_days (126)

        factor_returns_history = rng.standard_normal((T, 6)) * 0.01
        asset_returns_history = rng.standard_normal((T, n_assets)) * 0.01

        weights = np.array([0.4, 0.3, 0.3])
        realized_factor = rng.standard_normal(6) * 0.01
        realized_returns = np.array([0.01, -0.005, 0.003])

        result = engine.run_full_attribution(
            portfolio_id=portfolio_id,
            as_of_ts=as_of_ts,
            weights=weights,
            realized_returns=realized_returns,
            asset_returns_history=asset_returns_history,
            factor_returns_history=factor_returns_history,
            realized_factor_returns=realized_factor,
        )

        # All factor PnL should be zero
        for factor_name, pnl in result.factor_pnl.items():
            assert float(pnl) == 0.0

        # All PnL goes to idiosyncratic
        assert abs(float(result.total_pnl_bps - result.idio_pnl_bps)) < 0.01


# ---------------------------------------------------------------------------
# Tests: Retry Logic
# ---------------------------------------------------------------------------


class TestRetryLogic:
    """Tests for retry with exponential backoff."""

    def test_retry_succeeds_on_second_attempt(self, engine, portfolio_id, as_of_ts):
        """Attribution succeeds after one retry."""
        rng = np.random.default_rng(42)
        weights = np.array([0.5, 0.5])
        realized = np.array([0.01, -0.005])
        factor_returns = rng.standard_normal((253, 6)) * 0.01

        call_count = [0]

        def fetcher():
            call_count[0] += 1
            if call_count[0] == 1:
                raise FactorDataUnavailableError("Data not ready")
            return factor_returns

        with patch("time.sleep"):
            result = engine.run_factor_attribution_with_retry(
                portfolio_id, as_of_ts, weights, realized, fetcher
            )

        assert result.method == "factor_ff5_mom"
        assert call_count[0] == 2

    def test_retry_exhausted_raises(self, engine, portfolio_id, as_of_ts):
        """After max retries, raises FactorDataUnavailableError."""
        weights = np.array([0.5, 0.5])
        realized = np.array([0.01, -0.005])

        def fetcher():
            raise FactorDataUnavailableError("Data not ready")

        with patch("time.sleep"):
            with pytest.raises(FactorDataUnavailableError, match="after 3 retries"):
                engine.run_factor_attribution_with_retry(
                    portfolio_id, as_of_ts, weights, realized, fetcher
                )

    def test_retry_exponential_backoff_delays(self, engine, portfolio_id, as_of_ts):
        """Verify exponential backoff delays are correct."""
        weights = np.array([0.5, 0.5])
        realized = np.array([0.01, -0.005])
        delays = []

        def fetcher():
            raise FactorDataUnavailableError("Data not ready")

        with patch("time.sleep", side_effect=lambda d: delays.append(d)):
            with pytest.raises(FactorDataUnavailableError):
                engine.run_factor_attribution_with_retry(
                    portfolio_id, as_of_ts, weights, realized, fetcher
                )

        # Exponential backoff: 1, 2, 4
        assert delays == [1.0, 2.0, 4.0]


# ---------------------------------------------------------------------------
# Tests: Beta Estimation
# ---------------------------------------------------------------------------


class TestBetaEstimation:
    """Tests for estimate_betas_from_asset_returns."""

    def test_known_betas_recovered(self):
        """With known factor structure, betas should be recovered accurately."""
        rng = np.random.default_rng(42)
        T = 252
        n_assets = 3

        factor_returns = rng.standard_normal((T, 6)) * 0.01
        true_betas = np.array([
            [1.0, 0.5, -0.3, 0.2, 0.1, -0.4],
            [0.8, -0.2, 0.6, -0.1, 0.3, 0.2],
            [1.2, 0.3, 0.1, 0.5, -0.2, 0.7],
        ])

        # Generate asset returns from factor model (no noise for exact recovery)
        asset_returns = factor_returns @ true_betas.T

        engine = FactorAttributionEngine()
        betas, results = engine.estimate_betas_from_asset_returns(
            asset_returns, factor_returns
        )

        np.testing.assert_allclose(betas, true_betas, atol=1e-8)
        assert all(r is not None for r in results)

    def test_nan_assets_excluded(self):
        """Assets with NaN history below threshold are excluded."""
        rng = np.random.default_rng(42)
        T = 252
        n_assets = 3

        factor_returns = rng.standard_normal((T, 6)) * 0.01
        asset_returns = rng.standard_normal((T, n_assets)) * 0.01

        # Make asset 1 have only 50 valid days
        asset_returns[:202, 1] = np.nan

        engine = FactorAttributionEngine()
        betas, results = engine.estimate_betas_from_asset_returns(
            asset_returns, factor_returns
        )

        # Asset 1 should be excluded (all zeros)
        np.testing.assert_array_equal(betas[1, :], np.zeros(6))
        assert results[1] is None

        # Other assets should have non-zero betas
        assert not np.all(betas[0, :] == 0)
        assert not np.all(betas[2, :] == 0)

    def test_dimension_mismatch_raises(self):
        """Mismatched dimensions between asset and factor returns raises error."""
        rng = np.random.default_rng(42)
        asset_returns = rng.standard_normal((200, 3)) * 0.01
        factor_returns = rng.standard_normal((250, 6)) * 0.01

        engine = FactorAttributionEngine()
        with pytest.raises(ValueError, match="must have same length"):
            engine.estimate_betas_from_asset_returns(asset_returns, factor_returns)
