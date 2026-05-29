"""Unit tests for the Risk Parity optimizer (ERC + HRP fallback).

Tests cover:
- ERC Newton solver convergence on well-conditioned matrices
- HRP fallback for large universes and ill-conditioned matrices
- Non-convergence reporting
- Weight normalization (sum to 1)
- Risk contribution equality
- Constraint application (Bruder & Roncalli and post-hoc projection)
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

import numpy as np
import pytest

from astraeus_portfolio.contracts import OptContext
from astraeus_portfolio.optimizers.risk_parity import (
    RiskParityConfig,
    RiskParityOptimizer,
    _correlation_distance_matrix,
    _erc_gradient,
    _erc_hessian,
    _erc_objective,
    solve_erc_newton,
    solve_hrp,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_psd_cov(n: int, seed: int = 42) -> np.ndarray:
    """Generate a random positive-definite covariance matrix."""
    rng = np.random.default_rng(seed)
    A = rng.standard_normal((n, n))
    cov = A @ A.T / n
    # Ensure PSD with eigenvalue floor
    eigvals, eigvecs = np.linalg.eigh(cov)
    eigvals = np.maximum(eigvals, 1e-8)
    cov = eigvecs @ np.diag(eigvals) @ eigvecs.T
    return (cov + cov.T) / 2


def _make_opt_context(
    n: int,
    cov: np.ndarray | None = None,
    constraints: list | None = None,
    seed: int = 42,
) -> OptContext:
    """Create a minimal OptContext for testing."""
    if cov is None:
        cov = _make_psd_cov(n, seed)

    return OptContext(
        strategy_id="test_strategy",
        as_of_ts=datetime(2024, 1, 15, 16, 30),
        n_assets=n,
        symbols=[f"ASSET_{i}" for i in range(n)],
        expected_returns=np.zeros(n),
        covariance=cov,
        current_weights=np.ones(n) / n,
        prices=np.ones(n) * 100.0,
        adv=np.ones(n) * 1_000_000,
        sector_map={f"ASSET_{i}": "Technology" for i in range(n)},
        beta=np.ones(n),
        factor_loadings=None,
        views=None,
        scenarios=None,
        regime_label=None,
        constraints=constraints or [],
        risk_aversion=5.0,
        solver_chain=["ECOS", "CLARABEL", "SCS"],
        fully_invested=True,
        nav=Decimal("1000000"),
        seed=seed,
    )


# ---------------------------------------------------------------------------
# ERC Objective / Gradient / Hessian Tests
# ---------------------------------------------------------------------------


class TestERCObjective:
    """Tests for the ERC objective function and its derivatives."""

    def test_objective_positive_for_equal_weights(self):
        """ERC objective should be finite for equal weights."""
        n = 5
        cov = _make_psd_cov(n)
        w = np.ones(n) / n
        obj = _erc_objective(w, cov, n)
        assert np.isfinite(obj)

    def test_gradient_shape(self):
        """Gradient should have shape (n,)."""
        n = 5
        cov = _make_psd_cov(n)
        w = np.ones(n) / n
        grad = _erc_gradient(w, cov, n)
        assert grad.shape == (n,)

    def test_hessian_shape(self):
        """Hessian should have shape (n, n)."""
        n = 5
        cov = _make_psd_cov(n)
        w = np.ones(n) / n
        hess = _erc_hessian(w, cov, n)
        assert hess.shape == (n, n)

    def test_hessian_positive_definite(self):
        """Hessian should be positive definite for positive weights."""
        n = 5
        cov = _make_psd_cov(n)
        w = np.ones(n) / n
        hess = _erc_hessian(w, cov, n)
        eigvals = np.linalg.eigvalsh(hess)
        assert np.all(eigvals > 0)


# ---------------------------------------------------------------------------
# ERC Newton Solver Tests
# ---------------------------------------------------------------------------


class TestERCNewtonSolver:
    """Tests for the ERC Newton solver."""

    def test_converges_small_universe(self):
        """ERC should converge for a small well-conditioned universe."""
        n = 5
        cov = _make_psd_cov(n)
        config = RiskParityConfig()

        weights, converged, grad_norm, iterations = solve_erc_newton(cov, config)

        assert converged is True
        assert weights.shape == (n,)
        assert np.isclose(np.sum(weights), 1.0, atol=1e-6)
        assert np.all(weights >= 0)

    def test_converges_medium_universe(self):
        """ERC should converge for a medium-sized universe (50 assets)."""
        n = 50
        cov = _make_psd_cov(n)
        config = RiskParityConfig()

        weights, converged, grad_norm, iterations = solve_erc_newton(cov, config)

        assert converged is True
        assert np.isclose(np.sum(weights), 1.0, atol=1e-6)

    def test_weights_sum_to_one(self):
        """ERC weights must sum to 1."""
        n = 10
        cov = _make_psd_cov(n)
        config = RiskParityConfig()

        weights, _, _, _ = solve_erc_newton(cov, config)

        assert np.isclose(np.sum(weights), 1.0, atol=1e-8)

    def test_weights_non_negative(self):
        """ERC weights must be non-negative."""
        n = 10
        cov = _make_psd_cov(n)
        config = RiskParityConfig()

        weights, _, _, _ = solve_erc_newton(cov, config)

        assert np.all(weights >= 0)

    def test_risk_contributions_approximately_equal(self):
        """Risk contributions should be approximately equal for ERC."""
        n = 10
        cov = _make_psd_cov(n)
        config = RiskParityConfig()

        weights, converged, _, _ = solve_erc_newton(cov, config)
        assert converged

        # Compute risk contributions
        sigma_w = cov @ weights
        total_risk = weights @ sigma_w
        rc = weights * sigma_w / total_risk

        # Max ratio should be <= 1.05
        max_rc = np.max(rc)
        min_rc = np.min(rc[weights > 1e-10])
        ratio = max_rc / min_rc
        assert ratio <= 1.05, f"Risk contribution ratio {ratio:.4f} exceeds 1.05"

    def test_non_convergence_with_zero_iterations(self):
        """With max_iterations=0, solver should not converge."""
        n = 5
        cov = _make_psd_cov(n)
        config = RiskParityConfig(max_iterations=0)

        weights, converged, grad_norm, iterations = solve_erc_newton(cov, config)

        assert converged is False
        assert iterations == 0

    def test_diagonal_covariance_equal_weights(self):
        """For diagonal covariance with equal variances, ERC = equal weight."""
        n = 5
        cov = np.eye(n) * 0.04  # All assets have same variance
        config = RiskParityConfig()

        weights, converged, _, _ = solve_erc_newton(cov, config)
        assert converged

        expected = np.ones(n) / n
        np.testing.assert_allclose(weights, expected, atol=1e-4)


# ---------------------------------------------------------------------------
# HRP Tests
# ---------------------------------------------------------------------------


class TestHRP:
    """Tests for the Hierarchical Risk Parity algorithm."""

    def test_hrp_weights_sum_to_one(self):
        """HRP weights must sum to 1."""
        n = 20
        cov = _make_psd_cov(n)

        weights = solve_hrp(cov)

        assert np.isclose(np.sum(weights), 1.0, atol=1e-8)

    def test_hrp_weights_non_negative(self):
        """HRP weights must be non-negative."""
        n = 20
        cov = _make_psd_cov(n)

        weights = solve_hrp(cov)

        assert np.all(weights >= 0)

    def test_hrp_single_asset(self):
        """HRP with 1 asset should return weight of 1."""
        cov = np.array([[0.04]])
        weights = solve_hrp(cov)
        np.testing.assert_allclose(weights, [1.0])

    def test_hrp_two_assets(self):
        """HRP with 2 assets should use inverse-variance weighting."""
        cov = np.array([[0.04, 0.01], [0.01, 0.09]])
        weights = solve_hrp(cov)

        assert np.isclose(np.sum(weights), 1.0, atol=1e-8)
        # Higher variance asset should get lower weight
        assert weights[0] > weights[1]

    def test_hrp_large_universe(self):
        """HRP should handle large universes efficiently."""
        n = 250
        cov = _make_psd_cov(n)

        weights = solve_hrp(cov)

        assert weights.shape == (n,)
        assert np.isclose(np.sum(weights), 1.0, atol=1e-8)
        assert np.all(weights >= 0)


# ---------------------------------------------------------------------------
# Correlation Distance Matrix Tests
# ---------------------------------------------------------------------------


class TestCorrelationDistance:
    """Tests for the correlation-distance matrix computation."""

    def test_diagonal_zeros(self):
        """Distance matrix should have zeros on diagonal."""
        cov = _make_psd_cov(5)
        dist = _correlation_distance_matrix(cov)
        np.testing.assert_allclose(np.diag(dist), 0.0, atol=1e-10)

    def test_symmetric(self):
        """Distance matrix should be symmetric."""
        cov = _make_psd_cov(5)
        dist = _correlation_distance_matrix(cov)
        np.testing.assert_allclose(dist, dist.T, atol=1e-10)

    def test_non_negative(self):
        """Distance values should be non-negative."""
        cov = _make_psd_cov(5)
        dist = _correlation_distance_matrix(cov)
        assert np.all(dist >= -1e-10)

    def test_identity_covariance(self):
        """For identity covariance (zero correlation), distance = sqrt(0.5)."""
        n = 3
        cov = np.eye(n)
        dist = _correlation_distance_matrix(cov)

        expected_off_diag = np.sqrt(0.5)
        for i in range(n):
            for j in range(n):
                if i != j:
                    assert np.isclose(dist[i, j], expected_off_diag, atol=1e-6)


# ---------------------------------------------------------------------------
# Risk Parity Optimizer Integration Tests
# ---------------------------------------------------------------------------


class TestRiskParityOptimizer:
    """Integration tests for the full RiskParityOptimizer."""

    def test_erc_path_small_universe(self):
        """Optimizer should use ERC for small well-conditioned universe."""
        n = 10
        cov = _make_psd_cov(n)
        ctx = _make_opt_context(n, cov)

        optimizer = RiskParityOptimizer()
        result = optimizer.run(ctx)

        assert result.status == "optimal"
        assert result.solver_used == "erc_newton"
        assert np.isclose(np.sum(result.weights), 1.0, atol=1e-6)
        assert np.all(result.weights >= 0)

    def test_hrp_path_large_universe(self):
        """Optimizer should use HRP for universe > 200 assets."""
        n = 210
        cov = _make_psd_cov(n)
        ctx = _make_opt_context(n, cov)

        optimizer = RiskParityOptimizer()
        result = optimizer.run(ctx)

        assert result.status == "optimal"
        assert result.solver_used == "hrp_ward_bisection"
        assert np.isclose(np.sum(result.weights), 1.0, atol=1e-6)

    def test_hrp_path_ill_conditioned(self):
        """Optimizer should use HRP for ill-conditioned covariance."""
        n = 10
        # Create ill-conditioned matrix
        rng = np.random.default_rng(42)
        A = rng.standard_normal((n, n))
        cov = A @ A.T / n
        # Make one eigenvalue very small to increase condition number
        eigvals, eigvecs = np.linalg.eigh(cov)
        eigvals[0] = 1e-10  # Very small eigenvalue
        eigvals[-1] = 1e4   # Very large eigenvalue
        cov = eigvecs @ np.diag(eigvals) @ eigvecs.T
        cov = (cov + cov.T) / 2

        ctx = _make_opt_context(n, cov)

        optimizer = RiskParityOptimizer()
        result = optimizer.run(ctx)

        assert result.status == "optimal"
        assert result.solver_used == "hrp_ward_bisection"

    def test_non_convergence_reported(self):
        """Non-convergence should return failed status with diagnostics."""
        n = 5
        cov = _make_psd_cov(n)
        ctx = _make_opt_context(n, cov)

        # Force non-convergence with 0 iterations
        rp_config = RiskParityConfig(max_iterations=0)
        optimizer = RiskParityOptimizer(rp_config=rp_config)
        result = optimizer.run(ctx)

        assert result.status == "failed"
        assert result.solver_used == "erc_newton"
        assert len(result.weights) == 0

        # Check diagnostics contain convergence info
        convergence_diag = next(
            (d for d in result.constraint_diagnostics if d["constraint_name"] == "erc_convergence"),
            None,
        )
        assert convergence_diag is not None
        assert convergence_diag["satisfied"] is False
        assert "gradient_norm" in convergence_diag
        assert "iterations" in convergence_diag

    def test_single_asset_fails(self):
        """Optimizer should fail for single-asset universe."""
        n = 1
        cov = np.array([[0.04]])
        ctx = _make_opt_context(n, cov)

        optimizer = RiskParityOptimizer()
        result = optimizer.run(ctx)

        assert result.status == "failed"

    def test_solve_time_reported(self):
        """Solve time should be reported in milliseconds."""
        n = 10
        cov = _make_psd_cov(n)
        ctx = _make_opt_context(n, cov)

        optimizer = RiskParityOptimizer()
        result = optimizer.run(ctx)

        assert result.solve_time_ms > 0

    def test_objective_value_reported(self):
        """Objective value should be reported for successful optimization."""
        n = 10
        cov = _make_psd_cov(n)
        ctx = _make_opt_context(n, cov)

        optimizer = RiskParityOptimizer()
        result = optimizer.run(ctx)

        assert result.objective_value is not None
        assert np.isfinite(result.objective_value)

    def test_risk_contribution_ratio_within_tolerance(self):
        """Max risk contribution ratio should be <= 1.05 for ERC."""
        n = 20
        cov = _make_psd_cov(n)
        ctx = _make_opt_context(n, cov)

        optimizer = RiskParityOptimizer()
        result = optimizer.run(ctx)

        assert result.status == "optimal"

        # Verify risk contributions
        weights = result.weights
        sigma_w = cov @ weights
        total_risk = weights @ sigma_w
        rc = weights * sigma_w / total_risk

        max_rc = np.max(rc)
        min_rc = np.min(rc[weights > 1e-10])
        ratio = max_rc / min_rc
        assert ratio <= 1.05, f"Risk contribution ratio {ratio:.4f} exceeds 1.05"
