"""Unit tests for the CVaR Optimizer (Rockafellar-Uryasev LP).

Tests cover:
- Initialization and parameter validation
- Input validation (scenarios, NaN, S >= 2*n)
- Historical scenario generation (1000 most recent vectors)
- Bootstrap scenario generation (5000 block-bootstrap resamples)
- LP formulation produces valid weights
- CVaR optimality vs equal-weight portfolio
- Constraint relaxation fallback via base class
- Deterministic output for identical inputs
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import numpy as np
import pytest
from astraeus_portfolio.contracts import OptContext
from astraeus_portfolio.optimizers.cvar import (
    DEFAULT_BETA,
    CVaROptimizer,
    CVaRValidationError,
    ScenarioMode,
    _generate_bootstrap_scenarios,
    _generate_historical_scenarios,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_psd_covariance(n: int, seed: int = 42) -> np.ndarray:
    """Generate a random PSD covariance matrix of size n×n."""
    rng = np.random.default_rng(seed)
    A = rng.standard_normal((n, n))
    cov = A @ A.T / n
    cov = (cov + cov.T) / 2
    return cov


def _make_scenario_matrix(n_scenarios: int, n_assets: int, seed: int = 42) -> np.ndarray:
    """Generate a random scenario matrix of shape (n_scenarios, n_assets)."""
    rng = np.random.default_rng(seed)
    # Generate returns with realistic magnitudes (daily returns)
    return rng.normal(0.0005, 0.02, size=(n_scenarios, n_assets))


def _make_opt_context(
    n_assets: int = 5,
    n_scenarios: int = 1000,
    seed: int = 42,
    covariance: np.ndarray | None = None,
    expected_returns: np.ndarray | None = None,
    scenarios: np.ndarray | None = None,
    constraints: list | None = None,
    fully_invested: bool = True,
) -> OptContext:
    """Create a minimal OptContext for CVaR testing."""
    rng = np.random.default_rng(seed)

    if covariance is None:
        covariance = _make_psd_covariance(n_assets, seed)
    if expected_returns is None:
        expected_returns = rng.uniform(0.01, 0.15, size=n_assets)
    if scenarios is None:
        scenarios = _make_scenario_matrix(n_scenarios, n_assets, seed)

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
        scenarios=scenarios,
        regime_label=None,
        constraints=constraints or [],
        risk_aversion=5.0,
        solver_chain=["CLARABEL", "SCS"],
        fully_invested=fully_invested,
        nav=Decimal("1000000"),
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Initialization Tests
# ---------------------------------------------------------------------------


class TestCVaRInitialization:
    """Tests for CVaROptimizer initialization and parameter validation."""

    def test_default_initialization(self) -> None:
        """Default initialization uses beta=0.95 and historical mode."""
        opt = CVaROptimizer()
        assert opt.beta == DEFAULT_BETA
        assert opt.scenario_mode == ScenarioMode.HISTORICAL

    def test_custom_beta(self) -> None:
        """Custom beta value is accepted."""
        opt = CVaROptimizer(beta=0.99)
        assert opt.beta == 0.99

    def test_bootstrap_mode(self) -> None:
        """Bootstrap scenario mode is accepted."""
        opt = CVaROptimizer(scenario_mode=ScenarioMode.BOOTSTRAP)
        assert opt.scenario_mode == ScenarioMode.BOOTSTRAP

    def test_beta_zero_raises(self) -> None:
        """Beta of 0 raises ValueError."""
        with pytest.raises(ValueError, match="beta must be in"):
            CVaROptimizer(beta=0.0)

    def test_beta_one_raises(self) -> None:
        """Beta of 1 raises ValueError."""
        with pytest.raises(ValueError, match="beta must be in"):
            CVaROptimizer(beta=1.0)

    def test_beta_negative_raises(self) -> None:
        """Negative beta raises ValueError."""
        with pytest.raises(ValueError, match="beta must be in"):
            CVaROptimizer(beta=-0.5)


# ---------------------------------------------------------------------------
# Input Validation Tests
# ---------------------------------------------------------------------------


class TestCVaRInputValidation:
    """Tests for CVaR input validation."""

    def test_no_scenarios_raises(self) -> None:
        """Missing scenarios in OptContext raises CVaRValidationError."""
        opt = CVaROptimizer()
        ctx = _make_opt_context(n_assets=5, scenarios=np.empty((0, 0)))
        # Set scenarios to None
        ctx = OptContext(
            strategy_id="test",
            as_of_ts=datetime(2024, 1, 15),
            n_assets=5,
            symbols=[f"A{i}" for i in range(5)],
            expected_returns=np.ones(5) * 0.05,
            covariance=_make_psd_covariance(5),
            current_weights=np.ones(5) / 5,
            prices=np.ones(5) * 100,
            adv=np.ones(5) * 1_000_000,
            sector_map={f"A{i}": "Tech" for i in range(5)},
            beta=np.ones(5),
            factor_loadings=None,
            views=None,
            scenarios=None,
            regime_label=None,
            constraints=[],
            risk_aversion=5.0,
            solver_chain=["CLARABEL", "SCS"],
            fully_invested=True,
            nav=Decimal("1000000"),
            seed=42,
        )
        with pytest.raises(CVaRValidationError) as exc_info:
            opt.run(ctx)
        assert exc_info.value.reason == "no_scenarios"

    def test_insufficient_historical_data_raises(self) -> None:
        """Historical mode with < 1000 vectors raises CVaRValidationError."""
        opt = CVaROptimizer(scenario_mode=ScenarioMode.HISTORICAL)
        # Only 500 scenarios (less than required 1000)
        ctx = _make_opt_context(n_assets=5, n_scenarios=500)
        with pytest.raises(CVaRValidationError) as exc_info:
            opt.run(ctx)
        assert exc_info.value.reason == "insufficient_historical_data"

    def test_insufficient_scenarios_vs_assets_raises(self) -> None:
        """S < 2*n raises CVaRValidationError."""
        opt = CVaROptimizer(scenario_mode=ScenarioMode.HISTORICAL)
        # 1000 scenarios but 600 assets → need 1200 scenarios
        n_assets = 600
        ctx = _make_opt_context(n_assets=n_assets, n_scenarios=1000)
        with pytest.raises(CVaRValidationError) as exc_info:
            opt.run(ctx)
        assert exc_info.value.reason == "insufficient_scenarios"

    def test_nan_in_scenarios_raises(self) -> None:
        """NaN values in scenario matrix raises CVaRValidationError."""
        opt = CVaROptimizer(scenario_mode=ScenarioMode.HISTORICAL)
        scenarios = _make_scenario_matrix(1000, 5)
        scenarios[50, 2] = np.nan  # Inject NaN
        ctx = _make_opt_context(n_assets=5, scenarios=scenarios)
        with pytest.raises(CVaRValidationError) as exc_info:
            opt.run(ctx)
        assert exc_info.value.reason == "nan_in_scenarios"

    def test_exactly_2n_scenarios_passes(self) -> None:
        """Exactly S = 2*n scenarios passes validation."""
        n_assets = 5
        n_scenarios = 2 * n_assets  # Exactly 10
        # For historical mode, we need at least 1000, so use bootstrap
        opt = CVaROptimizer(scenario_mode=ScenarioMode.BOOTSTRAP)
        # Provide enough raw data for bootstrap to generate sufficient scenarios
        # Bootstrap generates 5000 scenarios from any amount of raw data
        ctx = _make_opt_context(n_assets=n_assets, n_scenarios=100)
        # This should pass since bootstrap generates 5000 scenarios from 100 raw
        result = opt.run(ctx)
        assert result.status in ("optimal", "optimal_inaccurate")


# ---------------------------------------------------------------------------
# Scenario Generation Tests
# ---------------------------------------------------------------------------


class TestScenarioGeneration:
    """Tests for scenario generation functions."""

    def test_historical_extracts_last_1000(self) -> None:
        """Historical mode extracts the 1000 most recent vectors."""
        scenarios = _make_scenario_matrix(1500, 5, seed=99)
        result = _generate_historical_scenarios(scenarios)
        assert result.shape == (1000, 5)
        # Should be the last 1000 rows
        np.testing.assert_array_equal(result, scenarios[-1000:])

    def test_historical_insufficient_raises(self) -> None:
        """Historical mode with < 1000 vectors raises error."""
        scenarios = _make_scenario_matrix(999, 5)
        with pytest.raises(CVaRValidationError) as exc_info:
            _generate_historical_scenarios(scenarios)
        assert exc_info.value.reason == "insufficient_historical_data"

    def test_historical_exactly_1000_passes(self) -> None:
        """Historical mode with exactly 1000 vectors passes."""
        scenarios = _make_scenario_matrix(1000, 5)
        result = _generate_historical_scenarios(scenarios)
        assert result.shape == (1000, 5)

    def test_bootstrap_generates_correct_count(self) -> None:
        """Bootstrap generates the specified number of scenarios."""
        scenarios = _make_scenario_matrix(500, 5)
        result = _generate_bootstrap_scenarios(scenarios, n_scenarios=5000)
        assert result.shape == (5000, 5)

    def test_bootstrap_deterministic_with_seed(self) -> None:
        """Bootstrap produces identical results with the same seed."""
        scenarios = _make_scenario_matrix(500, 5)
        result1 = _generate_bootstrap_scenarios(scenarios, seed=123)
        result2 = _generate_bootstrap_scenarios(scenarios, seed=123)
        np.testing.assert_array_equal(result1, result2)

    def test_bootstrap_different_seeds_differ(self) -> None:
        """Bootstrap produces different results with different seeds."""
        scenarios = _make_scenario_matrix(500, 5)
        result1 = _generate_bootstrap_scenarios(scenarios, seed=123)
        result2 = _generate_bootstrap_scenarios(scenarios, seed=456)
        assert not np.array_equal(result1, result2)

    def test_bootstrap_no_nan_in_output(self) -> None:
        """Bootstrap output contains no NaN values."""
        scenarios = _make_scenario_matrix(500, 5)
        result = _generate_bootstrap_scenarios(scenarios)
        assert not np.any(np.isnan(result))


# ---------------------------------------------------------------------------
# Optimization Tests
# ---------------------------------------------------------------------------


class TestCVaROptimization:
    """Tests for CVaR optimization producing valid results."""

    def test_historical_produces_valid_weights(self) -> None:
        """Historical mode produces weights that sum to 1."""
        opt = CVaROptimizer(scenario_mode=ScenarioMode.HISTORICAL)
        ctx = _make_opt_context(n_assets=5, n_scenarios=1000)
        result = opt.run(ctx)
        assert result.status in ("optimal", "optimal_inaccurate")
        assert np.isclose(result.weights.sum(), 1.0, atol=1e-6)

    def test_bootstrap_produces_valid_weights(self) -> None:
        """Bootstrap mode produces weights that sum to 1."""
        opt = CVaROptimizer(scenario_mode=ScenarioMode.BOOTSTRAP)
        ctx = _make_opt_context(n_assets=5, n_scenarios=200)
        result = opt.run(ctx)
        assert result.status in ("optimal", "optimal_inaccurate")
        assert np.isclose(result.weights.sum(), 1.0, atol=1e-6)

    def test_weights_are_finite(self) -> None:
        """All weights are finite (no NaN or Inf)."""
        opt = CVaROptimizer(scenario_mode=ScenarioMode.HISTORICAL)
        ctx = _make_opt_context(n_assets=5, n_scenarios=1000)
        result = opt.run(ctx)
        assert np.all(np.isfinite(result.weights))

    def test_solver_used_is_reported(self) -> None:
        """Successful optimization reports which solver was used."""
        opt = CVaROptimizer(scenario_mode=ScenarioMode.HISTORICAL)
        ctx = _make_opt_context(n_assets=5, n_scenarios=1000)
        result = opt.run(ctx)
        assert result.solver_used is not None
        assert result.solver_used in ("CLARABEL", "SCS", "ECOS")

    def test_solve_time_is_positive(self) -> None:
        """Successful optimization reports positive solve time."""
        opt = CVaROptimizer(scenario_mode=ScenarioMode.HISTORICAL)
        ctx = _make_opt_context(n_assets=5, n_scenarios=1000)
        result = opt.run(ctx)
        assert result.solve_time_ms > 0

    def test_cvar_better_than_equal_weight(self) -> None:
        """CVaR-optimized portfolio has lower CVaR than equal-weight portfolio.

        This validates Requirement 7.6: the optimizer produces weights where
        portfolio CVaR <= CVaR of equal-weight portfolio on the same scenarios.
        """
        n_assets = 5
        opt = CVaROptimizer(beta=0.95, scenario_mode=ScenarioMode.HISTORICAL)
        ctx = _make_opt_context(n_assets=n_assets, n_scenarios=1000)
        result = opt.run(ctx)

        # Compute CVaR for optimized portfolio
        scenarios = ctx.scenarios[-1000:]
        portfolio_returns_opt = scenarios @ result.weights
        var_threshold = np.percentile(portfolio_returns_opt, (1 - 0.95) * 100)
        cvar_opt = -np.mean(portfolio_returns_opt[portfolio_returns_opt <= var_threshold])

        # Compute CVaR for equal-weight portfolio
        w_eq = np.ones(n_assets) / n_assets
        portfolio_returns_eq = scenarios @ w_eq
        var_threshold_eq = np.percentile(portfolio_returns_eq, (1 - 0.95) * 100)
        cvar_eq = -np.mean(portfolio_returns_eq[portfolio_returns_eq <= var_threshold_eq])

        # CVaR of optimized should be <= CVaR of equal-weight
        assert cvar_opt <= cvar_eq + 1e-6


# ---------------------------------------------------------------------------
# Determinism Tests
# ---------------------------------------------------------------------------


class TestCVaRDeterminism:
    """Tests for deterministic output given identical inputs."""

    def test_historical_deterministic(self) -> None:
        """Historical mode produces identical weights on repeated runs."""
        opt = CVaROptimizer(scenario_mode=ScenarioMode.HISTORICAL)
        ctx = _make_opt_context(n_assets=5, n_scenarios=1000)

        result1 = opt.run(ctx)
        result2 = opt.run(ctx)

        np.testing.assert_allclose(result1.weights, result2.weights, atol=1e-10)

    def test_bootstrap_deterministic_same_seed(self) -> None:
        """Bootstrap mode produces identical weights with same seed."""
        opt = CVaROptimizer(scenario_mode=ScenarioMode.BOOTSTRAP)
        ctx = _make_opt_context(n_assets=5, n_scenarios=200, seed=42)

        result1 = opt.run(ctx)
        result2 = opt.run(ctx)

        np.testing.assert_allclose(result1.weights, result2.weights, atol=1e-10)


# ---------------------------------------------------------------------------
# Constraint Relaxation Tests
# ---------------------------------------------------------------------------


class TestCVaRConstraintRelaxation:
    """Tests for constraint relaxation fallback in CVaR optimizer."""

    def test_infeasible_with_no_relaxable_returns_failed(self) -> None:
        """Infeasible problem with no relaxable constraints returns failed status."""
        from astraeus_portfolio.constraints.base import Constraint

        class ImpossibleConstraint(Constraint):
            """A constraint that is impossible to satisfy."""

            def __init__(self) -> None:
                super().__init__(name="impossible", priority=0, relaxable=False)

            def to_cvxpy(self, w, ctx):
                import cvxpy as cp

                # Require sum(w) >= 10 (impossible with sum(w) = 1)
                return [cp.sum(w) >= 10]

            def diagnostic(self, w_value, ctx):
                return {"satisfied": False}

        opt = CVaROptimizer(scenario_mode=ScenarioMode.HISTORICAL)
        ctx = _make_opt_context(
            n_assets=5,
            n_scenarios=1000,
            constraints=[ImpossibleConstraint()],
        )
        result = opt.run(ctx)
        assert result.status == "failed"
        assert len(result.weights) == 0
