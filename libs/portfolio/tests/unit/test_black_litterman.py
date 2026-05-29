"""Unit tests for the Black-Litterman Optimizer.

Tests cover:
- Equilibrium return computation (Π = δΣw_mkt)
- Posterior computation with views via BL formula
- Omega computation via Idzorek's method
- Confidence capping at 0.99
- Condition number warning on contradictory views
- Expired view filtering (expires_at < as_of_ts)
- Fallback to equilibrium returns when no unexpired views
- Integration with MVO solver for final weights
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import numpy as np
from astraeus_portfolio.contracts import OptContext, View
from astraeus_portfolio.optimizers.black_litterman import (
    _DEFAULT_DELTA,
    BlackLittermanOptimizer,
    BLOptimizer,
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


def _make_opt_context(
    n_assets: int = 5,
    seed: int = 42,
    views: list[View] | None = None,
    current_weights: np.ndarray | None = None,
    covariance: np.ndarray | None = None,
) -> OptContext:
    """Create a minimal OptContext for BL testing."""
    rng = np.random.default_rng(seed)

    if covariance is None:
        covariance = _make_psd_covariance(n_assets, seed)
    if current_weights is None:
        current_weights = np.ones(n_assets) / n_assets

    return OptContext(
        strategy_id="test_bl_strategy",
        as_of_ts=datetime(2024, 6, 15, 16, 30),
        n_assets=n_assets,
        symbols=[f"ASSET_{i}" for i in range(n_assets)],
        expected_returns=rng.uniform(0.01, 0.15, size=n_assets),
        covariance=covariance,
        current_weights=current_weights,
        prices=rng.uniform(10, 500, size=n_assets),
        adv=rng.uniform(100_000, 10_000_000, size=n_assets),
        sector_map={f"ASSET_{i}": "Technology" for i in range(n_assets)},
        beta=rng.uniform(0.8, 1.2, size=n_assets),
        factor_loadings=None,
        views=views,
        scenarios=None,
        regime_label=None,
        constraints=[],
        risk_aversion=5.0,
        solver_chain=["CLARABEL", "SCS"],
        fully_invested=True,
        nav=Decimal("1000000"),
        seed=seed,
    )


def _make_view(
    n_assets: int = 5,
    n_views: int = 1,
    confidence: float = 0.5,
    expires_at: datetime | None = None,
    as_of_ts: datetime | None = None,
) -> View:
    """Create a simple view for testing."""
    if expires_at is None:
        expires_at = datetime(2024, 12, 31)
    if as_of_ts is None:
        as_of_ts = datetime(2024, 6, 1)

    # Simple view: asset 0 outperforms asset 1 by 5%
    P = []
    Q = []
    confs = []
    for _i in range(n_views):
        row = [0.0] * n_assets
        row[0] = 1.0
        row[1] = -1.0
        P.append(row)
        Q.append(0.05)
        confs.append(confidence)

    return View(
        view_id=f"test_view_{n_views}",
        as_of_ts=as_of_ts,
        source="manual",
        P=P,
        Q=Q,
        confidence=confs,
        rationale="Test view",
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------------
# Initialization Tests
# ---------------------------------------------------------------------------


class TestBLInitialization:
    """Tests for BlackLittermanOptimizer initialization."""

    def test_default_initialization(self) -> None:
        """Default initialization uses delta=2.5 and tau=None (auto)."""
        opt = BlackLittermanOptimizer()
        assert opt.delta == _DEFAULT_DELTA
        assert opt._tau_override is None
        assert opt.risk_aversion == 5.0

    def test_custom_delta(self) -> None:
        """Custom delta is stored correctly."""
        opt = BlackLittermanOptimizer(delta=3.0)
        assert opt.delta == 3.0

    def test_custom_tau(self) -> None:
        """Custom tau overrides the default 1/T."""
        opt = BlackLittermanOptimizer(tau=0.05)
        assert opt._tau_override == 0.05

    def test_alias_works(self) -> None:
        """BLOptimizer alias creates the same class."""
        opt = BLOptimizer()
        assert isinstance(opt, BlackLittermanOptimizer)


# ---------------------------------------------------------------------------
# Equilibrium Returns Tests
# ---------------------------------------------------------------------------


class TestEquilibriumReturns:
    """Tests for equilibrium return computation Π = δΣw_mkt."""

    def test_equilibrium_returns_shape(self) -> None:
        """Equilibrium returns have the correct shape (n,)."""
        opt = BlackLittermanOptimizer()
        n = 5
        sigma = _make_psd_covariance(n)
        w_mkt = np.ones(n) / n

        pi = opt._compute_equilibrium_returns(sigma, w_mkt)
        assert pi.shape == (n,)

    def test_equilibrium_returns_formula(self) -> None:
        """Equilibrium returns match Π = δΣw_mkt."""
        delta = 2.5
        opt = BlackLittermanOptimizer(delta=delta)
        n = 3
        sigma = np.array([[0.04, 0.01, 0.005], [0.01, 0.09, 0.02], [0.005, 0.02, 0.16]])
        w_mkt = np.array([0.5, 0.3, 0.2])

        pi = opt._compute_equilibrium_returns(sigma, w_mkt)
        expected = delta * sigma @ w_mkt
        np.testing.assert_allclose(pi, expected, atol=1e-12)

    def test_equilibrium_returns_scale_with_delta(self) -> None:
        """Doubling delta doubles equilibrium returns."""
        n = 5
        sigma = _make_psd_covariance(n)
        w_mkt = np.ones(n) / n

        opt1 = BlackLittermanOptimizer(delta=2.5)
        opt2 = BlackLittermanOptimizer(delta=5.0)

        pi1 = opt1._compute_equilibrium_returns(sigma, w_mkt)
        pi2 = opt2._compute_equilibrium_returns(sigma, w_mkt)

        np.testing.assert_allclose(pi2, 2.0 * pi1, atol=1e-12)


# ---------------------------------------------------------------------------
# View Filtering Tests
# ---------------------------------------------------------------------------


class TestViewFiltering:
    """Tests for expired view filtering."""

    def test_no_views_returns_empty(self) -> None:
        """None views returns empty list."""
        opt = BlackLittermanOptimizer()
        result = opt._filter_expired_views(None, datetime(2024, 6, 15))
        assert result == []

    def test_empty_views_returns_empty(self) -> None:
        """Empty views list returns empty list."""
        opt = BlackLittermanOptimizer()
        result = opt._filter_expired_views([], datetime(2024, 6, 15))
        assert result == []

    def test_unexpired_view_kept(self) -> None:
        """View with expires_at > as_of_ts is kept."""
        opt = BlackLittermanOptimizer()
        view = _make_view(expires_at=datetime(2024, 12, 31))
        result = opt._filter_expired_views([view], datetime(2024, 6, 15))
        assert len(result) == 1

    def test_expired_view_removed(self) -> None:
        """View with expires_at < as_of_ts is removed."""
        opt = BlackLittermanOptimizer()
        view = _make_view(expires_at=datetime(2024, 1, 1))
        result = opt._filter_expired_views([view], datetime(2024, 6, 15))
        assert len(result) == 0

    def test_view_expiring_at_as_of_ts_kept(self) -> None:
        """View with expires_at == as_of_ts is kept (not strictly less than)."""
        opt = BlackLittermanOptimizer()
        ts = datetime(2024, 6, 15, 16, 30)
        view = _make_view(expires_at=ts)
        result = opt._filter_expired_views([view], ts)
        assert len(result) == 1

    def test_mixed_views_filtered_correctly(self) -> None:
        """Mix of expired and unexpired views is filtered correctly."""
        opt = BlackLittermanOptimizer()
        as_of = datetime(2024, 6, 15)
        view_expired = _make_view(expires_at=datetime(2024, 1, 1))
        view_valid = _make_view(expires_at=datetime(2024, 12, 31))

        result = opt._filter_expired_views([view_expired, view_valid], as_of)
        assert len(result) == 1
        assert result[0].expires_at == datetime(2024, 12, 31)


# ---------------------------------------------------------------------------
# Omega Computation Tests
# ---------------------------------------------------------------------------


class TestOmegaComputation:
    """Tests for Omega computation via Idzorek's method."""

    def test_omega_is_diagonal(self) -> None:
        """Omega matrix is diagonal."""
        opt = BlackLittermanOptimizer()
        n = 5
        sigma = _make_psd_covariance(n)
        tau = 1.0 / 252
        P = np.zeros((2, n))
        P[0, 0] = 1.0
        P[0, 1] = -1.0
        P[1, 2] = 1.0
        confidences = np.array([0.5, 0.7])

        omega = opt._compute_omega_idzorek(P, sigma, tau, confidences)

        # Check diagonal
        assert omega.shape == (2, 2)
        assert np.allclose(omega, np.diag(np.diag(omega)))

    def test_omega_positive_diagonal(self) -> None:
        """Omega diagonal elements are positive."""
        opt = BlackLittermanOptimizer()
        n = 5
        sigma = _make_psd_covariance(n)
        tau = 1.0 / 252
        P = np.zeros((1, n))
        P[0, 0] = 1.0
        confidences = np.array([0.5])

        omega = opt._compute_omega_idzorek(P, sigma, tau, confidences)
        assert omega[0, 0] > 0

    def test_higher_confidence_lower_omega(self) -> None:
        """Higher confidence produces lower Omega (less uncertainty)."""
        opt = BlackLittermanOptimizer()
        n = 5
        sigma = _make_psd_covariance(n)
        tau = 1.0 / 252
        P = np.zeros((1, n))
        P[0, 0] = 1.0

        omega_low = opt._compute_omega_idzorek(P, sigma, tau, np.array([0.3]))
        omega_high = opt._compute_omega_idzorek(P, sigma, tau, np.array([0.9]))

        assert omega_high[0, 0] < omega_low[0, 0]

    def test_confidence_at_cap_produces_small_omega(self) -> None:
        """Confidence at 0.99 produces very small Omega."""
        opt = BlackLittermanOptimizer()
        n = 5
        sigma = _make_psd_covariance(n)
        tau = 1.0 / 252
        P = np.zeros((1, n))
        P[0, 0] = 1.0

        omega = opt._compute_omega_idzorek(P, sigma, tau, np.array([0.99]))
        # (1/0.99 - 1) ≈ 0.0101, so omega should be very small
        assert omega[0, 0] > 0
        assert omega[0, 0] < 0.1  # Very small relative to view variance


# ---------------------------------------------------------------------------
# Confidence Capping Tests
# ---------------------------------------------------------------------------


class TestConfidenceCapping:
    """Tests for confidence capping at 0.99."""

    def test_confidence_capped_in_view_validator(self) -> None:
        """View validator caps confidence at 0.99."""
        view = View(
            view_id="test",
            as_of_ts=datetime(2024, 6, 1),
            source="manual",
            P=[[1.0, -1.0, 0.0]],
            Q=[0.05],
            confidence=[1.0],  # Should be capped to 0.99
            rationale="Test",
            expires_at=datetime(2024, 12, 31),
        )
        assert view.confidence[0] == 0.99

    def test_confidence_below_cap_unchanged(self) -> None:
        """Confidence below 0.99 is unchanged."""
        view = View(
            view_id="test",
            as_of_ts=datetime(2024, 6, 1),
            source="manual",
            P=[[1.0, -1.0, 0.0]],
            Q=[0.05],
            confidence=[0.75],
            rationale="Test",
            expires_at=datetime(2024, 12, 31),
        )
        assert view.confidence[0] == 0.75


# ---------------------------------------------------------------------------
# Fallback to Equilibrium Tests
# ---------------------------------------------------------------------------


class TestFallbackToEquilibrium:
    """Tests for fallback to equilibrium returns when no views available."""

    def test_no_views_uses_equilibrium(self) -> None:
        """With no views, optimizer uses equilibrium returns and produces valid weights."""
        opt = BlackLittermanOptimizer()
        ctx = _make_opt_context(n_assets=5, views=None)
        result = opt.run(ctx)

        assert result.status in ("optimal", "optimal_inaccurate")
        assert np.isclose(result.weights.sum(), 1.0, atol=1e-6)

    def test_all_expired_views_uses_equilibrium(self) -> None:
        """When all views are expired, falls back to equilibrium returns."""
        opt = BlackLittermanOptimizer()
        expired_view = _make_view(
            n_assets=5,
            expires_at=datetime(2024, 1, 1),  # Before as_of_ts
        )
        ctx = _make_opt_context(n_assets=5, views=[expired_view])
        result = opt.run(ctx)

        assert result.status in ("optimal", "optimal_inaccurate")
        assert np.isclose(result.weights.sum(), 1.0, atol=1e-6)

    def test_empty_views_list_uses_equilibrium(self) -> None:
        """Empty views list falls back to equilibrium returns."""
        opt = BlackLittermanOptimizer()
        ctx = _make_opt_context(n_assets=5, views=[])
        result = opt.run(ctx)

        assert result.status in ("optimal", "optimal_inaccurate")
        assert np.isclose(result.weights.sum(), 1.0, atol=1e-6)


# ---------------------------------------------------------------------------
# Posterior Computation Tests
# ---------------------------------------------------------------------------


class TestPosteriorComputation:
    """Tests for BL posterior return computation."""

    def test_posterior_with_views_produces_valid_weights(self) -> None:
        """BL with views produces valid weights summing to 1."""
        opt = BlackLittermanOptimizer()
        view = _make_view(n_assets=5, confidence=0.6)
        ctx = _make_opt_context(n_assets=5, views=[view])
        result = opt.run(ctx)

        assert result.status in ("optimal", "optimal_inaccurate")
        assert np.isclose(result.weights.sum(), 1.0, atol=1e-6)

    def test_high_confidence_view_tilts_weights(self) -> None:
        """High confidence view tilts weights toward the view."""
        n = 5
        # Use a well-conditioned diagonal covariance to avoid numerical issues
        cov = np.diag([0.04, 0.04, 0.04, 0.04, 0.04])
        opt = BlackLittermanOptimizer()

        # View: asset 0 outperforms asset 1 by 5%
        view = _make_view(n_assets=n, confidence=0.8)
        ctx = _make_opt_context(
            n_assets=n,
            views=[view],
            current_weights=np.ones(n) / n,
            covariance=cov,
        )
        result = opt.run(ctx)

        # Asset 0 should have higher weight than asset 1 due to the view
        assert result.weights[0] > result.weights[1]

    def test_low_confidence_view_minimal_impact(self) -> None:
        """Low confidence view has minimal impact on weights vs equilibrium."""
        n = 5
        cov = _make_psd_covariance(n, seed=42)
        w_mkt = np.ones(n) / n

        # Run without views (equilibrium)
        opt_eq = BlackLittermanOptimizer()
        ctx_eq = _make_opt_context(n_assets=n, views=None, covariance=cov)
        result_eq = opt_eq.run(ctx_eq)

        # Run with very low confidence view
        view = _make_view(n_assets=n, confidence=0.01)
        ctx_view = _make_opt_context(n_assets=n, views=[view], covariance=cov)
        result_view = opt_eq.run(ctx_view)

        # Weights should be similar (low confidence = minimal impact)
        # Allow some tolerance since even low confidence has some effect
        diff = np.abs(result_eq.weights - result_view.weights).max()
        assert diff < 0.15  # Relatively small difference

    def test_multiple_views_combined(self) -> None:
        """Multiple views are combined correctly."""
        n = 5
        opt = BlackLittermanOptimizer()

        # Two views with different picking matrices
        view1 = View(
            view_id="v1",
            as_of_ts=datetime(2024, 6, 1),
            source="manual",
            P=[[1.0, -1.0, 0.0, 0.0, 0.0]],
            Q=[0.03],
            confidence=[0.7],
            rationale="Asset 0 > Asset 1",
            expires_at=datetime(2024, 12, 31),
        )
        view2 = View(
            view_id="v2",
            as_of_ts=datetime(2024, 6, 1),
            source="manual",
            P=[[0.0, 0.0, 1.0, -1.0, 0.0]],
            Q=[0.02],
            confidence=[0.6],
            rationale="Asset 2 > Asset 3",
            expires_at=datetime(2024, 12, 31),
        )

        ctx = _make_opt_context(n_assets=n, views=[view1, view2])
        result = opt.run(ctx)

        assert result.status in ("optimal", "optimal_inaccurate")
        assert np.isclose(result.weights.sum(), 1.0, atol=1e-6)


# ---------------------------------------------------------------------------
# Condition Number Warning Tests
# ---------------------------------------------------------------------------


class TestConditionNumberWarning:
    """Tests for condition number warning on contradictory views."""

    def test_well_conditioned_views_no_warning(self, caplog) -> None:
        """Well-conditioned views do not trigger a warning."""
        import logging

        n = 5
        opt = BlackLittermanOptimizer()
        view = _make_view(n_assets=n, confidence=0.5)
        ctx = _make_opt_context(n_assets=n, views=[view])

        with caplog.at_level(logging.WARNING):
            result = opt.run(ctx)

        # Should not have condition number warning
        assert "high_condition_number" not in caplog.text


# ---------------------------------------------------------------------------
# Tau Computation Tests
# ---------------------------------------------------------------------------


class TestTauComputation:
    """Tests for tau parameter computation."""

    def test_default_tau_is_1_over_252(self) -> None:
        """Default tau is 1/T = 1/252."""
        opt = BlackLittermanOptimizer()
        ctx = _make_opt_context(n_assets=5)
        tau = opt._get_tau(ctx)
        assert np.isclose(tau, 1.0 / 252)

    def test_custom_tau_overrides_default(self) -> None:
        """Custom tau overrides the default 1/T."""
        opt = BlackLittermanOptimizer(tau=0.05)
        ctx = _make_opt_context(n_assets=5)
        tau = opt._get_tau(ctx)
        assert tau == 0.05


# ---------------------------------------------------------------------------
# Integration with MVO Tests
# ---------------------------------------------------------------------------


class TestBLMVOIntegration:
    """Tests for BL integration with MVO solver."""

    def test_result_has_solver_info(self) -> None:
        """BL result includes solver information from MVO."""
        opt = BlackLittermanOptimizer()
        ctx = _make_opt_context(n_assets=5, views=None)
        result = opt.run(ctx)

        assert result.solver_used is not None
        assert result.solve_time_ms > 0

    def test_result_weights_are_numpy_array(self) -> None:
        """BL result weights are a numpy array."""
        opt = BlackLittermanOptimizer()
        ctx = _make_opt_context(n_assets=5, views=None)
        result = opt.run(ctx)

        assert isinstance(result.weights, np.ndarray)
        assert result.weights.shape == (5,)

    def test_deterministic_output(self) -> None:
        """BL produces identical weights on repeated runs."""
        opt = BlackLittermanOptimizer()
        view = _make_view(n_assets=5, confidence=0.6)
        ctx = _make_opt_context(n_assets=5, views=[view])

        result1 = opt.run(ctx)
        result2 = opt.run(ctx)

        np.testing.assert_allclose(result1.weights, result2.weights, atol=1e-10)
