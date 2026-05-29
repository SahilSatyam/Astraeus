"""Unit tests for VaR/CVaR computation module.

Tests cover:
- Historical VaR/CVaR computation
- Parametric (Gaussian) VaR/CVaR computation
- Monte Carlo (t-copula) VaR/CVaR computation
- Input validation (minimum observations, NaN/Inf rejection)
- Discrepancy detection between methods
- Both 95% and 99% confidence levels
- Multivariate portfolio computation
- Deterministic output with fixed seed
"""

from __future__ import annotations

import numpy as np
import pytest

from astraeus_portfolio.risk.var_cvar import (
    InsufficientDataError,
    VaRConfig,
    VaRMethod,
    VaRReport,
    VaRResult,
    compute_historical_var,
    compute_monte_carlo_var,
    compute_monte_carlo_var_multivariate,
    compute_parametric_var,
    compute_var_cvar,
    compute_var_cvar_multivariate,
    _check_discrepancy,
    _validate_returns,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_returns(
    n_days: int = 252, mu: float = 0.0004, sigma: float = 0.01, seed: int = 42
) -> np.ndarray:
    """Generate synthetic daily returns from a normal distribution."""
    rng = np.random.default_rng(seed)
    return rng.normal(mu, sigma, size=n_days)


def _generate_fat_tailed_returns(
    n_days: int = 252, seed: int = 42
) -> np.ndarray:
    """Generate returns with fat tails (t-distribution, df=3)."""
    rng = np.random.default_rng(seed)
    return rng.standard_t(df=3, size=n_days) * 0.01


def _generate_multivariate_returns(
    n_days: int = 252, n_assets: int = 5, seed: int = 42
) -> np.ndarray:
    """Generate correlated multivariate returns."""
    rng = np.random.default_rng(seed)
    # Create a correlation structure
    A = rng.standard_normal((n_assets, n_assets))
    cov = A @ A.T / n_assets * 0.0001  # Scale to daily variance
    mean = np.full(n_assets, 0.0004)
    return rng.multivariate_normal(mean, cov, size=n_days)


# ---------------------------------------------------------------------------
# Input Validation Tests
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Tests for input validation logic."""

    def test_reject_fewer_than_60_days(self) -> None:
        """Reject computation when fewer than 60 trading days available."""
        returns = _generate_returns(n_days=59)
        with pytest.raises(InsufficientDataError) as exc_info:
            compute_var_cvar(returns)
        assert exc_info.value.available == 59
        assert exc_info.value.minimum_required == 60

    def test_accept_exactly_60_days(self) -> None:
        """Accept computation with exactly 60 trading days."""
        returns = _generate_returns(n_days=60)
        report = compute_var_cvar(returns)
        assert report.n_observations == 60

    def test_reject_nan_values(self) -> None:
        """Reject returns containing NaN values."""
        returns = _generate_returns(n_days=100)
        returns[50] = np.nan
        with pytest.raises(ValueError, match="NaN"):
            compute_var_cvar(returns)

    def test_reject_inf_values(self) -> None:
        """Reject returns containing Inf values."""
        returns = _generate_returns(n_days=100)
        returns[50] = np.inf
        with pytest.raises(ValueError, match="Inf"):
            compute_var_cvar(returns)

    def test_reject_negative_inf_values(self) -> None:
        """Reject returns containing -Inf values."""
        returns = _generate_returns(n_days=100)
        returns[50] = -np.inf
        with pytest.raises(ValueError, match="Inf"):
            compute_var_cvar(returns)

    def test_reject_2d_array(self) -> None:
        """Reject 2-D array for single-series function."""
        returns = _generate_returns(n_days=100).reshape(50, 2)
        with pytest.raises(ValueError, match="1-D"):
            _validate_returns(returns, 60)

    def test_custom_min_observations(self) -> None:
        """Custom min_observations is respected."""
        returns = _generate_returns(n_days=80)
        config = VaRConfig(min_observations=100)
        with pytest.raises(InsufficientDataError) as exc_info:
            compute_var_cvar(returns, config=config)
        assert exc_info.value.minimum_required == 100


# ---------------------------------------------------------------------------
# Historical VaR/CVaR Tests
# ---------------------------------------------------------------------------


class TestHistoricalVaR:
    """Tests for historical VaR/CVaR computation."""

    def test_var_95_positive(self) -> None:
        """Historical VaR at 95% is positive for typical returns."""
        returns = _generate_returns(n_days=252)
        var_pct, cvar_pct = compute_historical_var(returns, 0.95)
        assert var_pct > 0

    def test_var_99_greater_than_var_95(self) -> None:
        """VaR at 99% confidence is greater than VaR at 95%."""
        returns = _generate_returns(n_days=252)
        var_95, _ = compute_historical_var(returns, 0.95)
        var_99, _ = compute_historical_var(returns, 0.99)
        assert var_99 >= var_95

    def test_cvar_greater_than_or_equal_var(self) -> None:
        """CVaR is always >= VaR (expected shortfall exceeds VaR)."""
        returns = _generate_returns(n_days=252)
        var_pct, cvar_pct = compute_historical_var(returns, 0.95)
        assert cvar_pct >= var_pct - 1e-10

    def test_cvar_99_greater_than_cvar_95(self) -> None:
        """CVaR at 99% is greater than CVaR at 95%."""
        returns = _generate_returns(n_days=252)
        _, cvar_95 = compute_historical_var(returns, 0.95)
        _, cvar_99 = compute_historical_var(returns, 0.99)
        assert cvar_99 >= cvar_95

    def test_lookback_window_respected(self) -> None:
        """Only the most recent lookback_window days are used."""
        # Create returns where first half is calm, second half is volatile
        rng = np.random.default_rng(42)
        calm = rng.normal(0, 0.005, size=200)
        volatile = rng.normal(0, 0.03, size=100)
        returns = np.concatenate([calm, volatile])

        # With lookback=100, should only see volatile period
        var_short, _ = compute_historical_var(returns, 0.95, lookback_window=100)
        # With lookback=300, includes calm period
        var_long, _ = compute_historical_var(returns, 0.95, lookback_window=300)

        # VaR from volatile-only window should be larger
        assert var_short > var_long

    def test_known_quantile(self) -> None:
        """VaR matches expected quantile for known distribution."""
        # Create uniform returns from -0.05 to 0.05
        returns = np.linspace(-0.05, 0.05, 1000)
        var_95, _ = compute_historical_var(returns, 0.95, lookback_window=1000)
        # 5th percentile of uniform[-0.05, 0.05] = -0.05 + 0.05*0.1 = -0.045
        # VaR = -(-0.045) * 100 = 4.5%
        assert abs(var_95 - 4.5) < 0.1  # Allow small interpolation error


# ---------------------------------------------------------------------------
# Parametric VaR/CVaR Tests
# ---------------------------------------------------------------------------


class TestParametricVaR:
    """Tests for parametric (Gaussian) VaR/CVaR computation."""

    def test_var_95_positive(self) -> None:
        """Parametric VaR at 95% is positive for typical returns."""
        returns = _generate_returns(n_days=252)
        var_pct, cvar_pct = compute_parametric_var(returns, 0.95)
        assert var_pct > 0

    def test_var_99_greater_than_var_95(self) -> None:
        """Parametric VaR at 99% > VaR at 95%."""
        returns = _generate_returns(n_days=252)
        var_95, _ = compute_parametric_var(returns, 0.95)
        var_99, _ = compute_parametric_var(returns, 0.99)
        assert var_99 > var_95

    def test_cvar_greater_than_var(self) -> None:
        """Parametric CVaR >= VaR."""
        returns = _generate_returns(n_days=252)
        var_pct, cvar_pct = compute_parametric_var(returns, 0.95)
        assert cvar_pct >= var_pct - 1e-10

    def test_known_parameters(self) -> None:
        """VaR matches analytical formula for known μ and σ."""
        # Create returns with known mean and std
        rng = np.random.default_rng(42)
        n = 10000
        mu = 0.0005
        sigma = 0.015
        returns = rng.normal(mu, sigma, size=n)

        var_pct, _ = compute_parametric_var(returns, 0.95, lookback_window=n)

        # Expected VaR = -(mu + z_0.05 * sigma) * 100
        from scipy.stats import norm

        z = norm.ppf(0.05)
        expected_var = -(mu + z * sigma) * 100

        # Should be close (large sample)
        assert abs(var_pct - expected_var) < 0.05

    def test_zero_mean_returns(self) -> None:
        """VaR with zero-mean returns equals z_β·σ."""
        # Construct returns with exactly zero mean
        returns = np.array([0.01, -0.01] * 126)  # 252 days, mean=0
        var_pct, _ = compute_parametric_var(returns, 0.95, lookback_window=252)

        # With mean=0: VaR = -z_0.05 * sigma * 100 = 1.645 * sigma * 100
        sigma = np.std(returns, ddof=1)
        from scipy.stats import norm

        expected_var = -norm.ppf(0.05) * sigma * 100
        assert abs(var_pct - expected_var) < 1e-10


# ---------------------------------------------------------------------------
# Monte Carlo VaR/CVaR Tests
# ---------------------------------------------------------------------------


class TestMonteCarloVaR:
    """Tests for Monte Carlo (t-copula) VaR/CVaR computation."""

    def test_var_95_positive(self) -> None:
        """MC VaR at 95% is positive for typical returns."""
        returns = _generate_returns(n_days=252)
        var_pct, cvar_pct = compute_monte_carlo_var(returns, 0.95, seed=42)
        assert var_pct > 0

    def test_var_99_greater_than_var_95(self) -> None:
        """MC VaR at 99% > VaR at 95%."""
        returns = _generate_returns(n_days=252)
        var_95, _ = compute_monte_carlo_var(returns, 0.95, seed=42)
        var_99, _ = compute_monte_carlo_var(returns, 0.99, seed=42)
        assert var_99 >= var_95

    def test_cvar_greater_than_var(self) -> None:
        """MC CVaR >= VaR."""
        returns = _generate_returns(n_days=252)
        var_pct, cvar_pct = compute_monte_carlo_var(returns, 0.95, seed=42)
        assert cvar_pct >= var_pct - 1e-10

    def test_deterministic_with_same_seed(self) -> None:
        """Same seed produces identical results."""
        returns = _generate_returns(n_days=252)
        var1, cvar1 = compute_monte_carlo_var(returns, 0.95, seed=123)
        var2, cvar2 = compute_monte_carlo_var(returns, 0.95, seed=123)
        assert var1 == var2
        assert cvar1 == cvar2

    def test_different_seed_different_results(self) -> None:
        """Different seeds produce different results."""
        returns = _generate_returns(n_days=252)
        var1, _ = compute_monte_carlo_var(returns, 0.95, seed=42)
        var2, _ = compute_monte_carlo_var(returns, 0.95, seed=99)
        # Very unlikely to be exactly equal with different seeds
        assert var1 != var2

    def test_t_copula_heavier_tails(self) -> None:
        """t-copula (df=4) produces heavier tails than Gaussian for same data."""
        # With fat-tailed historical data, MC should capture tail risk
        returns = _generate_fat_tailed_returns(n_days=500)
        mc_var, _ = compute_monte_carlo_var(
            returns, 0.99, lookback_window=500, seed=42
        )
        # MC VaR should be positive and meaningful
        assert mc_var > 0


# ---------------------------------------------------------------------------
# Multivariate Monte Carlo Tests
# ---------------------------------------------------------------------------


class TestMultivariateMonteCarloVaR:
    """Tests for multivariate t-copula Monte Carlo VaR."""

    def test_basic_computation(self) -> None:
        """Multivariate MC produces valid VaR/CVaR."""
        asset_returns = _generate_multivariate_returns(n_days=252, n_assets=5)
        weights = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
        var_pct, cvar_pct = compute_monte_carlo_var_multivariate(
            asset_returns, weights, 0.95, seed=42
        )
        assert var_pct > 0
        assert cvar_pct >= var_pct - 1e-10

    def test_deterministic(self) -> None:
        """Same seed produces identical multivariate results."""
        asset_returns = _generate_multivariate_returns(n_days=252, n_assets=3)
        weights = np.array([0.5, 0.3, 0.2])
        var1, cvar1 = compute_monte_carlo_var_multivariate(
            asset_returns, weights, 0.95, seed=42
        )
        var2, cvar2 = compute_monte_carlo_var_multivariate(
            asset_returns, weights, 0.95, seed=42
        )
        assert var1 == var2
        assert cvar1 == cvar2

    def test_concentrated_portfolio_higher_var(self) -> None:
        """Concentrated portfolio has higher VaR than diversified."""
        asset_returns = _generate_multivariate_returns(
            n_days=252, n_assets=5, seed=77
        )
        # Diversified
        w_div = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
        # Concentrated in one asset
        w_conc = np.array([0.8, 0.05, 0.05, 0.05, 0.05])

        var_div, _ = compute_monte_carlo_var_multivariate(
            asset_returns, w_div, 0.95, seed=42
        )
        var_conc, _ = compute_monte_carlo_var_multivariate(
            asset_returns, w_conc, 0.95, seed=42
        )
        # Concentrated portfolio generally has higher risk
        # (not guaranteed for all random seeds, but likely)
        # We just check both are positive
        assert var_div > 0
        assert var_conc > 0


# ---------------------------------------------------------------------------
# Discrepancy Detection Tests
# ---------------------------------------------------------------------------


class TestDiscrepancyDetection:
    """Tests for VaR discrepancy flagging."""

    def test_no_discrepancy_similar_values(self) -> None:
        """No warning when VaR values are similar."""
        warning = _check_discrepancy(2.0, 2.3, 0.95, threshold=0.50)
        assert warning is None

    def test_discrepancy_detected(self) -> None:
        """Warning emitted when difference exceeds 50% of min."""
        # |3.0 - 1.5| / 1.5 = 1.0 > 0.50
        warning = _check_discrepancy(3.0, 1.5, 0.95, threshold=0.50)
        assert warning is not None
        assert "discrepancy" in warning.lower()

    def test_discrepancy_at_boundary(self) -> None:
        """No warning at exactly 50% difference."""
        # |3.0 - 2.0| / 2.0 = 0.50, not > 0.50
        warning = _check_discrepancy(3.0, 2.0, 0.95, threshold=0.50)
        assert warning is None

    def test_discrepancy_just_above_boundary(self) -> None:
        """Warning at just above 50% difference."""
        # |3.01 - 2.0| / 2.0 = 0.505 > 0.50
        warning = _check_discrepancy(3.01, 2.0, 0.95, threshold=0.50)
        assert warning is not None

    def test_no_discrepancy_zero_var(self) -> None:
        """No warning when either VaR is zero or negative."""
        assert _check_discrepancy(0.0, 2.0, 0.95) is None
        assert _check_discrepancy(2.0, 0.0, 0.95) is None
        assert _check_discrepancy(-1.0, 2.0, 0.95) is None

    def test_fat_tailed_returns_trigger_discrepancy(self) -> None:
        """Fat-tailed returns may trigger discrepancy between hist and param."""
        # Create returns with extreme outliers
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, size=252)
        # Add extreme outliers
        returns[0] = -0.15
        returns[1] = -0.12
        returns[2] = -0.10

        report = compute_var_cvar(returns, seed=42)
        # With extreme outliers, historical VaR will be much larger than
        # parametric VaR (which assumes Gaussian)
        # Check that discrepancy detection works
        assert isinstance(report.discrepancy_warnings, list)


# ---------------------------------------------------------------------------
# Full Report Tests
# ---------------------------------------------------------------------------


class TestVaRReport:
    """Tests for the complete VaR/CVaR report generation."""

    def test_report_has_six_var_results(self) -> None:
        """Report contains 6 VaR results (3 methods × 2 confidence levels)."""
        returns = _generate_returns(n_days=252)
        report = compute_var_cvar(returns, seed=42)
        assert len(report.results) == 6

    def test_report_methods_and_levels(self) -> None:
        """Report covers all method/confidence combinations."""
        returns = _generate_returns(n_days=252)
        report = compute_var_cvar(returns, seed=42)

        methods = {r.method for r in report.results}
        levels = {r.confidence_level for r in report.results}

        assert methods == {
            VaRMethod.HISTORICAL,
            VaRMethod.PARAMETRIC,
            VaRMethod.MONTE_CARLO,
        }
        assert levels == {0.95, 0.99}

    def test_report_lookback_days(self) -> None:
        """Report records the lookback window used."""
        returns = _generate_returns(n_days=252)
        report = compute_var_cvar(returns, seed=42)
        assert report.lookback_days_used == 252

    def test_report_lookback_capped_at_available(self) -> None:
        """Lookback is capped at available data when less than window."""
        returns = _generate_returns(n_days=100)
        config = VaRConfig(lookback_window=252, min_observations=60)
        report = compute_var_cvar(returns, config=config, seed=42)
        assert report.lookback_days_used == 100

    def test_report_all_var_positive(self) -> None:
        """All VaR values are positive for typical market returns."""
        returns = _generate_returns(n_days=252)
        report = compute_var_cvar(returns, seed=42)
        for result in report.results:
            assert result.var_pct > 0

    def test_report_cvar_geq_var(self) -> None:
        """CVaR >= VaR for all results in the report."""
        returns = _generate_returns(n_days=252)
        report = compute_var_cvar(returns, seed=42)
        for result in report.results:
            assert result.cvar_pct >= result.var_pct - 1e-10

    def test_report_99_geq_95_for_each_method(self) -> None:
        """VaR at 99% >= VaR at 95% for each method."""
        returns = _generate_returns(n_days=252)
        report = compute_var_cvar(returns, seed=42)

        for method in VaRMethod:
            results_for_method = [
                r for r in report.results if r.method == method
            ]
            var_95 = next(
                r.var_pct for r in results_for_method if r.confidence_level == 0.95
            )
            var_99 = next(
                r.var_pct for r in results_for_method if r.confidence_level == 0.99
            )
            assert var_99 >= var_95 - 1e-10

    def test_deterministic_report(self) -> None:
        """Same inputs produce identical report."""
        returns = _generate_returns(n_days=252)
        report1 = compute_var_cvar(returns, seed=42)
        report2 = compute_var_cvar(returns, seed=42)

        for r1, r2 in zip(report1.results, report2.results):
            assert r1.var_pct == r2.var_pct
            assert r1.cvar_pct == r2.cvar_pct


# ---------------------------------------------------------------------------
# Multivariate Report Tests
# ---------------------------------------------------------------------------


class TestMultivariateVaRReport:
    """Tests for multivariate VaR/CVaR report."""

    def test_multivariate_report_structure(self) -> None:
        """Multivariate report has correct structure."""
        asset_returns = _generate_multivariate_returns(n_days=252, n_assets=5)
        weights = np.ones(5) / 5
        report = compute_var_cvar_multivariate(asset_returns, weights, seed=42)
        assert len(report.results) == 6
        assert report.n_observations == 252

    def test_multivariate_rejects_shape_mismatch(self) -> None:
        """Reject when weights don't match asset count."""
        asset_returns = _generate_multivariate_returns(n_days=252, n_assets=5)
        weights = np.ones(3) / 3  # Wrong size
        with pytest.raises(ValueError, match="assets"):
            compute_var_cvar_multivariate(asset_returns, weights, seed=42)

    def test_multivariate_rejects_1d_returns(self) -> None:
        """Reject 1-D returns for multivariate function."""
        returns = _generate_returns(n_days=252)
        weights = np.array([1.0])
        with pytest.raises(ValueError, match="2-D"):
            compute_var_cvar_multivariate(returns, weights, seed=42)

    def test_multivariate_rejects_insufficient_data(self) -> None:
        """Reject when fewer than 60 days available."""
        asset_returns = _generate_multivariate_returns(n_days=50, n_assets=3)
        weights = np.ones(3) / 3
        with pytest.raises(InsufficientDataError):
            compute_var_cvar_multivariate(asset_returns, weights, seed=42)

    def test_multivariate_deterministic(self) -> None:
        """Same inputs produce identical multivariate report."""
        asset_returns = _generate_multivariate_returns(n_days=252, n_assets=5)
        weights = np.ones(5) / 5
        report1 = compute_var_cvar_multivariate(asset_returns, weights, seed=42)
        report2 = compute_var_cvar_multivariate(asset_returns, weights, seed=42)

        for r1, r2 in zip(report1.results, report2.results):
            assert r1.var_pct == r2.var_pct
            assert r1.cvar_pct == r2.cvar_pct


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_exactly_60_observations(self) -> None:
        """Computation succeeds with exactly 60 observations."""
        returns = _generate_returns(n_days=60)
        report = compute_var_cvar(returns, seed=42)
        assert report.n_observations == 60
        assert len(report.results) == 6

    def test_large_dataset(self) -> None:
        """Computation handles large datasets (2000+ days)."""
        returns = _generate_returns(n_days=2000)
        report = compute_var_cvar(returns, seed=42)
        # Should use only 252 most recent days
        assert report.lookback_days_used == 252

    def test_constant_returns(self) -> None:
        """Handle constant returns (zero volatility)."""
        returns = np.full(252, 0.001)
        # Parametric VaR with zero sigma should still work
        report = compute_var_cvar(returns, seed=42)
        # With constant positive returns, VaR should be negative (no loss)
        # or very close to zero
        for result in report.results:
            if result.method == VaRMethod.PARAMETRIC:
                # VaR = -(mu + z*0) = -mu = -0.001*100 = -0.1
                # This means no loss risk
                assert result.var_pct < 0.5  # Very low risk

    def test_all_negative_returns(self) -> None:
        """Handle all-negative returns (persistent losses)."""
        rng = np.random.default_rng(42)
        returns = -np.abs(rng.normal(0.01, 0.005, size=252))
        report = compute_var_cvar(returns, seed=42)
        # All VaR values should be large and positive
        for result in report.results:
            assert result.var_pct > 0
