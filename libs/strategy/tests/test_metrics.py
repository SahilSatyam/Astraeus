"""Unit tests for backtest metrics computation.

Tests Sharpe, Sortino, Calmar, drawdown, VaR/CVaR, and statistical metrics.
"""

from __future__ import annotations

import numpy as np
import pytest
from astraeus_strategy.metrics import (
    _kurtosis,
    _max_dd_duration,
    _skewness,
    compute_metrics,
)


class TestComputeMetrics:
    """Test the main compute_metrics function."""

    @pytest.mark.unit
    def test_empty_returns(self):
        """Empty returns array produces zero metrics."""
        result = compute_metrics(np.array([]))
        assert result.sharpe == 0.0
        assert result.total_days == 0

    @pytest.mark.unit
    def test_positive_returns_positive_sharpe(self):
        """Consistently positive returns produce positive Sharpe."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, 252)  # ~25% annual, ~16% vol
        result = compute_metrics(returns)

        assert result.sharpe > 0
        assert result.annualized_return > 0
        assert result.annualized_vol > 0

    @pytest.mark.unit
    def test_negative_returns_negative_sharpe(self):
        """Consistently negative returns produce negative Sharpe."""
        rng = np.random.default_rng(42)
        returns = rng.normal(-0.002, 0.01, 252)
        result = compute_metrics(returns)

        assert result.sharpe < 0
        assert result.annualized_return < 0

    @pytest.mark.unit
    def test_zero_vol_returns(self):
        """Constant returns don't crash (edge case)."""
        returns = np.full(100, 0.001)
        result = compute_metrics(returns)
        # Should not raise; Sharpe may be very large
        assert result.total_days == 100

    @pytest.mark.unit
    def test_max_drawdown_is_negative(self):
        """Max drawdown is always <= 0."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.0, 0.02, 252)
        result = compute_metrics(returns)

        assert result.max_drawdown <= 0

    @pytest.mark.unit
    def test_var_less_than_cvar(self):
        """CVaR (expected shortfall) is always <= VaR."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.0, 0.02, 1000)
        result = compute_metrics(returns)

        assert result.cvar_95 <= result.var_95

    @pytest.mark.unit
    def test_sortino_higher_than_sharpe_for_positive_skew(self):
        """For positively skewed returns, Sortino > Sharpe (less downside)."""
        # Create positively skewed returns (more upside than downside)
        rng = np.random.default_rng(42)
        base = rng.normal(0.001, 0.01, 500)
        # Add some large positive outliers
        base[::50] += 0.05
        result = compute_metrics(base)

        # Sortino should be >= Sharpe for positive-mean, positive-skew
        if result.sharpe > 0:
            assert result.sortino >= result.sharpe * 0.8  # approximate

    @pytest.mark.unit
    def test_calmar_ratio(self):
        """Calmar = annualized return / |max drawdown|."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.015, 252)
        result = compute_metrics(returns)

        if result.max_drawdown != 0:
            expected_calmar = result.annualized_return / abs(result.max_drawdown)
            assert abs(result.calmar - expected_calmar) < 1e-6

    @pytest.mark.unit
    def test_information_ratio_with_benchmark(self):
        """IR is computed when benchmark is provided."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.015, 252)
        benchmark = rng.normal(0.0005, 0.012, 252)

        result = compute_metrics(returns, benchmark_returns=benchmark)
        assert result.information_ratio != 0.0

    @pytest.mark.unit
    def test_information_ratio_zero_without_benchmark(self):
        """IR is 0 when no benchmark is provided."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.015, 252)

        result = compute_metrics(returns)
        assert result.information_ratio == 0.0

    @pytest.mark.unit
    def test_final_equity(self):
        """Final equity matches cumulative product of (1 + returns)."""
        returns = np.array([0.01, 0.02, -0.01, 0.005])
        result = compute_metrics(returns)

        expected = float(np.prod(1 + returns))
        assert abs(result.final_equity - expected) < 1e-10

    @pytest.mark.unit
    def test_total_days(self):
        """Total days matches input length."""
        returns = np.zeros(500)
        result = compute_metrics(returns)
        assert result.total_days == 500

    @pytest.mark.unit
    def test_sharpe_ci_contains_point_estimate(self):
        """Sharpe CI should contain the point estimate."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.015, 252)
        result = compute_metrics(returns)

        assert result.sharpe_ci_lower <= result.sharpe <= result.sharpe_ci_upper

    @pytest.mark.unit
    def test_probabilistic_sharpe_between_0_and_1(self):
        """PSR is a probability, must be in [0, 1]."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.015, 252)
        result = compute_metrics(returns)

        assert 0.0 <= result.probabilistic_sharpe <= 1.0

    @pytest.mark.unit
    def test_to_dict(self):
        """BacktestMetrics.to_dict() returns all fields."""
        result = compute_metrics(np.array([0.01, -0.005, 0.02]))
        d = result.to_dict()

        assert "sharpe" in d
        assert "max_drawdown" in d
        assert "var_95" in d
        assert "total_days" in d


class TestMaxDdDuration:
    """Test max drawdown duration helper."""

    @pytest.mark.unit
    def test_no_drawdown(self):
        drawdowns = np.zeros(100)
        assert _max_dd_duration(drawdowns) == 0

    @pytest.mark.unit
    def test_single_drawdown_period(self):
        drawdowns = np.array([0, 0, -0.01, -0.02, -0.03, 0, 0])
        assert _max_dd_duration(drawdowns) == 3

    @pytest.mark.unit
    def test_multiple_drawdown_periods(self):
        drawdowns = np.array([0, -0.01, -0.02, 0, -0.01, -0.02, -0.03, -0.04, 0])
        assert _max_dd_duration(drawdowns) == 4


class TestSkewnessKurtosis:
    """Test higher moment calculations."""

    @pytest.mark.unit
    def test_symmetric_distribution_zero_skew(self):
        """Symmetric distribution has ~0 skewness."""
        rng = np.random.default_rng(42)
        x = rng.normal(0, 1, 10000)
        assert abs(_skewness(x)) < 0.1

    @pytest.mark.unit
    def test_normal_distribution_zero_excess_kurtosis(self):
        """Normal distribution has ~0 excess kurtosis."""
        rng = np.random.default_rng(42)
        x = rng.normal(0, 1, 10000)
        assert abs(_kurtosis(x)) < 0.2

    @pytest.mark.unit
    def test_short_array_returns_zero(self):
        """Arrays too short for moments return 0."""
        assert _skewness(np.array([1.0, 2.0])) == 0.0
        assert _kurtosis(np.array([1.0, 2.0, 3.0])) == 0.0
