"""Unit tests for the Mean-Variance Optimizer.

Tests cover:
- Three modes: tangency, min-variance, target-return
- Input validation (PSD covariance, universe >= 2 assets)
- risk_aversion parameter validation
- Constraint relaxation fallback via base class
- Deterministic output for identical inputs
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import numpy as np
import pytest
from astraeus_portfolio.contracts import OptContext
from astraeus_portfolio.optimizers.mvo import (
    MeanVarianceOptimizer,
    MVOMode,
    MVOValidationError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_psd_covariance(n: int, seed: int = 42) -> np.ndarray:
    """Generate a random PSD covariance matrix of size n×n."""
    rng = np.random.default_rng(seed)
    A = rng.standard_normal((n, n))
    cov = A @ A.T / n
    # Ensure symmetry
    cov = (cov + cov.T) / 2
    return cov


def _make_opt_context(
    n_assets: int = 5,
    risk_aversion: float = 5.0,
    seed: int = 42,
    covariance: np.ndarray | None = None,
    expected_returns: np.ndarray | None = None,
    constraints: list | None = None,
    fully_invested: bool = True,
) -> OptContext:
    """Create a minimal OptContext for testing."""
    rng = np.random.default_rng(seed)

    if covariance is None:
        covariance = _make_psd_covariance(n_assets, seed)
    if expected_returns is None:
        expected_returns = rng.uniform(0.01, 0.15, size=n_assets)

    return OptContext(
        strategy_id="test_strategy",
        as_of_ts=datetime(2024, 1, 15, 16, 30),
        n_assets=n_assets,
        symbols=[f"ASSET_{i}" for i in range(n_assets)],
        expected_returns=expected_returns,
        covariance=covariance,
        current_weights=np.ones(n_assets) / n_assets,
        prices=rng.uniform(10, 500, size=n_assets),
        adv=rng.uniform(100_000, 10_000_000, size=n_assets),
        sector_map={f"ASSET_{i}": "Technology" for i in range(n_assets)},
        beta=rng.uniform(0.8, 1.2, size=n_assets),
        factor_loadings=None,
        views=None,
        scenarios=None,
        regime_label=None,
        constraints=constraints or [],
        risk_aversion=risk_aversion,
        solver_chain=["CLARABEL", "SCS"],
        fully_invested=fully_invested,
        nav=Decimal("1000000"),
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Initialization Tests
# ---------------------------------------------------------------------------


class TestMVOInitialization:
    """Tests for MeanVarianceOptimizer initialization and parameter validation."""

    def test_default_initialization(self) -> None:
        """Default initialization uses tangency mode with risk_aversion=5.0."""
        opt = MeanVarianceOptimizer()
        assert opt.mode == MVOMode.TANGENCY
        assert opt.risk_aversion == 5.0
        assert opt.target_return is None

    def test_min_variance_mode(self) -> None:
        """Min-variance mode initializes without target_return."""
        opt = MeanVarianceOptimizer(mode=MVOMode.MIN_VARIANCE)
        assert opt.mode == MVOMode.MIN_VARIANCE

    def test_target_return_mode(self) -> None:
        """Target-return mode requires a valid target_return."""
        opt = MeanVarianceOptimizer(mode=MVOMode.TARGET_RETURN, target_return=0.08)
        assert opt.mode == MVOMode.TARGET_RETURN
        assert opt.target_return == 0.08

    def test_target_return_mode_missing_target_raises(self) -> None:
        """Target-return mode without target_return raises ValueError."""
        with pytest.raises(ValueError, match="target_return is required"):
            MeanVarianceOptimizer(mode=MVOMode.TARGET_RETURN)

    def test_target_return_out_of_range_raises(self) -> None:
        """Target-return outside [0.0, 1.0] raises ValueError."""
        with pytest.raises(ValueError, match="target_return must be in"):
            MeanVarianceOptimizer(mode=MVOMode.TARGET_RETURN, target_return=1.5)

    def test_target_return_negative_raises(self) -> None:
        """Negative target_return raises ValueError."""
        with pytest.raises(ValueError, match="target_return must be in"):
            MeanVarianceOptimizer(mode=MVOMode.TARGET_RETURN, target_return=-0.1)

    def test_risk_aversion_too_low_raises(self) -> None:
        """risk_aversion below 0.1 raises ValueError."""
        with pytest.raises(ValueError, match="risk_aversion must be in"):
            MeanVarianceOptimizer(risk_aversion=0.05)

    def test_risk_aversion_too_high_raises(self) -> None:
        """risk_aversion above 100.0 raises ValueError."""
        with pytest.raises(ValueError, match="risk_aversion must be in"):
            MeanVarianceOptimizer(risk_aversion=150.0)

    def test_risk_aversion_boundary_low(self) -> None:
        """risk_aversion=0.1 is valid (lower boundary)."""
        opt = MeanVarianceOptimizer(risk_aversion=0.1)
        assert opt.risk_aversion == 0.1

    def test_risk_aversion_boundary_high(self) -> None:
        """risk_aversion=100.0 is valid (upper boundary)."""
        opt = MeanVarianceOptimizer(risk_aversion=100.0)
        assert opt.risk_aversion == 100.0


# ---------------------------------------------------------------------------
# Input Validation Tests
# ---------------------------------------------------------------------------


class TestMVOInputValidation:
    """Tests for MVO input validation (PSD covariance, universe size)."""

    def test_single_asset_raises(self) -> None:
        """Universe with 1 asset raises MVOValidationError."""
        opt = MeanVarianceOptimizer()
        ctx = _make_opt_context(n_assets=1)
        # Need to fix the covariance for 1 asset
        ctx = OptContext(
            strategy_id="test",
            as_of_ts=datetime(2024, 1, 15),
            n_assets=1,
            symbols=["A"],
            expected_returns=np.array([0.1]),
            covariance=np.array([[0.04]]),
            current_weights=np.array([1.0]),
            prices=np.array([100.0]),
            adv=np.array([1_000_000.0]),
            sector_map={"A": "Tech"},
            beta=np.array([1.0]),
            factor_loadings=None,
            views=None,
            scenarios=None,
            regime_label=None,
            constraints=[],
            risk_aversion=5.0,
            solver_chain=["CLARABEL"],
            fully_invested=True,
            nav=Decimal("1000000"),
            seed=42,
        )
        with pytest.raises(MVOValidationError) as exc_info:
            opt.run(ctx)
        assert exc_info.value.reason == "insufficient_assets"

    def test_non_psd_covariance_raises(self) -> None:
        """Non-PSD covariance matrix raises MVOValidationError."""
        opt = MeanVarianceOptimizer()
        # Create a non-PSD matrix (negative eigenvalue)
        cov = np.array([[1.0, 2.0], [2.0, 1.0]])  # eigenvalues: 3, -1
        ctx = _make_opt_context(n_assets=2, covariance=cov)
        with pytest.raises(MVOValidationError) as exc_info:
            opt.run(ctx)
        assert exc_info.value.reason == "covariance_not_psd"

    def test_asymmetric_covariance_raises(self) -> None:
        """Asymmetric covariance matrix raises MVOValidationError."""
        opt = MeanVarianceOptimizer()
        cov = np.array([[1.0, 0.5], [0.3, 1.0]])  # Not symmetric
        ctx = _make_opt_context(n_assets=2, covariance=cov)
        with pytest.raises(MVOValidationError) as exc_info:
            opt.run(ctx)
        assert exc_info.value.reason == "covariance_not_symmetric"

    def test_covariance_shape_mismatch_raises(self) -> None:
        """Covariance matrix with wrong shape raises MVOValidationError."""
        opt = MeanVarianceOptimizer()
        cov = _make_psd_covariance(3)  # 3×3 but context has 5 assets
        ctx = _make_opt_context(n_assets=5, covariance=cov)
        with pytest.raises(MVOValidationError) as exc_info:
            opt.run(ctx)
        assert exc_info.value.reason == "covariance_shape_mismatch"

    def test_valid_psd_covariance_passes(self) -> None:
        """Valid PSD covariance passes validation and produces a result."""
        opt = MeanVarianceOptimizer()
        ctx = _make_opt_context(n_assets=5)
        result = opt.run(ctx)
        assert result.status in ("optimal", "optimal_inaccurate")
        assert len(result.weights) == 5


# ---------------------------------------------------------------------------
# Tangency Mode Tests
# ---------------------------------------------------------------------------


class TestMVOTangency:
    """Tests for tangency mode: minimize λ·w'Σw - μ'w."""

    def test_tangency_produces_valid_weights(self) -> None:
        """Tangency mode produces weights that sum to 1."""
        opt = MeanVarianceOptimizer(mode=MVOMode.TANGENCY, risk_aversion=5.0)
        ctx = _make_opt_context(n_assets=5)
        result = opt.run(ctx)
        assert result.status in ("optimal", "optimal_inaccurate")
        assert np.isclose(result.weights.sum(), 1.0, atol=1e-6)

    def test_tangency_higher_risk_aversion_lower_variance(self) -> None:
        """Higher risk aversion produces lower portfolio variance."""
        ctx = _make_opt_context(n_assets=5)
        cov = ctx.covariance

        opt_low = MeanVarianceOptimizer(mode=MVOMode.TANGENCY, risk_aversion=1.0)
        opt_high = MeanVarianceOptimizer(mode=MVOMode.TANGENCY, risk_aversion=50.0)

        # Need to set risk_aversion in context too
        ctx_low = _make_opt_context(n_assets=5, risk_aversion=1.0)
        ctx_high = _make_opt_context(n_assets=5, risk_aversion=50.0)

        result_low = opt_low.run(ctx_low)
        result_high = opt_high.run(ctx_high)

        var_low = result_low.weights @ cov @ result_low.weights
        var_high = result_high.weights @ cov @ result_high.weights

        # Higher risk aversion should produce lower variance
        assert var_high < var_low

    def test_tangency_uses_expected_returns(self) -> None:
        """Tangency mode tilts toward assets with higher expected returns."""
        # Create a simple 2-asset case with one clearly dominant asset
        cov = np.array([[0.04, 0.01], [0.01, 0.04]])  # Equal variance
        mu = np.array([0.15, 0.02])  # Asset 0 has much higher return

        opt = MeanVarianceOptimizer(mode=MVOMode.TANGENCY, risk_aversion=2.0)
        ctx = _make_opt_context(n_assets=2, covariance=cov, expected_returns=mu, risk_aversion=2.0)
        result = opt.run(ctx)

        # Asset 0 should have higher weight due to higher expected return
        assert result.weights[0] > result.weights[1]


# ---------------------------------------------------------------------------
# Min-Variance Mode Tests
# ---------------------------------------------------------------------------


class TestMVOMinVariance:
    """Tests for min-variance mode: minimize w'Σw."""

    def test_min_variance_produces_valid_weights(self) -> None:
        """Min-variance mode produces weights that sum to 1."""
        opt = MeanVarianceOptimizer(mode=MVOMode.MIN_VARIANCE)
        ctx = _make_opt_context(n_assets=5)
        result = opt.run(ctx)
        assert result.status in ("optimal", "optimal_inaccurate")
        assert np.isclose(result.weights.sum(), 1.0, atol=1e-6)

    def test_min_variance_ignores_expected_returns(self) -> None:
        """Min-variance produces same weights regardless of expected returns."""
        opt = MeanVarianceOptimizer(mode=MVOMode.MIN_VARIANCE)

        # Two contexts with different expected returns but same covariance
        cov = _make_psd_covariance(3, seed=99)
        mu1 = np.array([0.05, 0.10, 0.15])
        mu2 = np.array([0.20, 0.01, 0.08])

        ctx1 = _make_opt_context(n_assets=3, covariance=cov, expected_returns=mu1)
        ctx2 = _make_opt_context(n_assets=3, covariance=cov, expected_returns=mu2)

        result1 = opt.run(ctx1)
        result2 = opt.run(ctx2)

        # Weights should be identical since expected returns are not used
        np.testing.assert_allclose(result1.weights, result2.weights, atol=1e-6)

    def test_min_variance_lower_than_equal_weight(self) -> None:
        """Min-variance portfolio has lower variance than equal-weight portfolio."""
        opt = MeanVarianceOptimizer(mode=MVOMode.MIN_VARIANCE)
        ctx = _make_opt_context(n_assets=5)
        result = opt.run(ctx)

        cov = ctx.covariance
        w_opt = result.weights
        w_eq = np.ones(5) / 5

        var_opt = w_opt @ cov @ w_opt
        var_eq = w_eq @ cov @ w_eq

        assert var_opt <= var_eq + 1e-10


# ---------------------------------------------------------------------------
# Target-Return Mode Tests
# ---------------------------------------------------------------------------


class TestMVOTargetReturn:
    """Tests for target-return mode: minimize w'Σw subject to μ'w >= r_target."""

    def test_target_return_produces_valid_weights(self) -> None:
        """Target-return mode produces weights that sum to 1."""
        opt = MeanVarianceOptimizer(mode=MVOMode.TARGET_RETURN, target_return=0.05)
        ctx = _make_opt_context(n_assets=5)
        result = opt.run(ctx)
        assert result.status in ("optimal", "optimal_inaccurate")
        assert np.isclose(result.weights.sum(), 1.0, atol=1e-6)

    def test_target_return_meets_target(self) -> None:
        """Target-return mode achieves at least the target return."""
        target = 0.05
        opt = MeanVarianceOptimizer(mode=MVOMode.TARGET_RETURN, target_return=target)
        ctx = _make_opt_context(n_assets=5)
        result = opt.run(ctx)

        achieved_return = ctx.expected_returns @ result.weights
        # Should meet or exceed target (within solver tolerance)
        assert achieved_return >= target - 1e-6

    def test_target_return_higher_target_higher_variance(self) -> None:
        """Higher target return leads to higher portfolio variance."""
        cov = _make_psd_covariance(5, seed=77)

        opt_low = MeanVarianceOptimizer(mode=MVOMode.TARGET_RETURN, target_return=0.03)
        opt_high = MeanVarianceOptimizer(mode=MVOMode.TARGET_RETURN, target_return=0.10)

        # Use expected returns that make both targets feasible
        mu = np.array([0.05, 0.08, 0.12, 0.15, 0.20])
        ctx = _make_opt_context(n_assets=5, covariance=cov, expected_returns=mu)

        result_low = opt_low.run(ctx)
        result_high = opt_high.run(ctx)

        var_low = result_low.weights @ cov @ result_low.weights
        var_high = result_high.weights @ cov @ result_high.weights

        # Higher target return should require more risk
        assert var_high >= var_low - 1e-10


# ---------------------------------------------------------------------------
# Determinism Tests
# ---------------------------------------------------------------------------


class TestMVODeterminism:
    """Tests for deterministic output given identical inputs."""

    def test_tangency_deterministic(self) -> None:
        """Tangency mode produces identical weights on repeated runs."""
        opt = MeanVarianceOptimizer(mode=MVOMode.TANGENCY, risk_aversion=5.0)
        ctx = _make_opt_context(n_assets=5)

        result1 = opt.run(ctx)
        result2 = opt.run(ctx)

        np.testing.assert_allclose(result1.weights, result2.weights, atol=1e-10)

    def test_min_variance_deterministic(self) -> None:
        """Min-variance mode produces identical weights on repeated runs."""
        opt = MeanVarianceOptimizer(mode=MVOMode.MIN_VARIANCE)
        ctx = _make_opt_context(n_assets=5)

        result1 = opt.run(ctx)
        result2 = opt.run(ctx)

        np.testing.assert_allclose(result1.weights, result2.weights, atol=1e-10)

    def test_target_return_deterministic(self) -> None:
        """Target-return mode produces identical weights on repeated runs."""
        opt = MeanVarianceOptimizer(mode=MVOMode.TARGET_RETURN, target_return=0.05)
        ctx = _make_opt_context(n_assets=5)

        result1 = opt.run(ctx)
        result2 = opt.run(ctx)

        np.testing.assert_allclose(result1.weights, result2.weights, atol=1e-10)


# ---------------------------------------------------------------------------
# Solver Chain and Fallback Tests
# ---------------------------------------------------------------------------


class TestMVOSolverFallback:
    """Tests for solver chain and constraint relaxation fallback."""

    def test_infeasible_returns_failed_status(self) -> None:
        """Infeasible problem (impossible target with box constraints) returns failed status."""
        from astraeus_portfolio.constraints.base import Constraint

        # Create a simple box constraint that limits weights to [0, 0.5]
        class SimpleBoxConstraint(Constraint):
            def __init__(self) -> None:
                super().__init__(name="box", priority=0, relaxable=False)

            def to_cvxpy(self, w, ctx):
                return [w >= 0, w <= 0.5]

            def diagnostic(self, w_value, ctx):
                return {
                    "satisfied": bool(np.all(w_value >= -1e-6) and np.all(w_value <= 0.5 + 1e-6))
                }

        # Set target return higher than achievable with box constraints
        # Max achievable return with w_i in [0, 0.5] and sum(w)=1:
        # With 5 assets and max weight 0.5, best case is 0.5*max + 0.5*second_max
        opt = MeanVarianceOptimizer(mode=MVOMode.TARGET_RETURN, target_return=0.99)
        # All expected returns are low — max achievable is ~0.04
        mu = np.array([0.01, 0.02, 0.03, 0.04, 0.05])
        ctx = _make_opt_context(
            n_assets=5,
            expected_returns=mu,
            constraints=[SimpleBoxConstraint()],
        )
        result = opt.run(ctx)

        # Should fail since no feasible portfolio can achieve 99% return
        # with box constraints limiting weights to [0, 0.5]
        assert result.status == "failed"
        assert len(result.weights) == 0

    def test_solver_used_is_reported(self) -> None:
        """Successful optimization reports which solver was used."""
        opt = MeanVarianceOptimizer(mode=MVOMode.MIN_VARIANCE)
        ctx = _make_opt_context(n_assets=5)
        result = opt.run(ctx)

        assert result.solver_used is not None
        assert result.solver_used in ("CLARABEL", "SCS", "ECOS")

    def test_solve_time_is_positive(self) -> None:
        """Successful optimization reports positive solve time."""
        opt = MeanVarianceOptimizer(mode=MVOMode.MIN_VARIANCE)
        ctx = _make_opt_context(n_assets=5)
        result = opt.run(ctx)

        assert result.solve_time_ms > 0
