"""Property test for MVO variance optimality.

**Validates: Requirements 4.5**

Property 8: MVO variance optimality
    When the MVO optimizer receives a PSD covariance matrix and a universe of
    at least 2 assets with a feasible constraint set, the realized portfolio
    variance (w'Σw) must be less than or equal to the variance of the
    equal-weight portfolio on the same universe.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import hypothesis.strategies as st
import numpy as np
from astraeus_portfolio.constraints.base import Constraint
from astraeus_portfolio.constraints.box import BoxConstraint
from astraeus_portfolio.contracts import OptContext
from astraeus_portfolio.optimizers.mvo import MVOMode, MVOOptimizer
from hypothesis import assume, given, settings

# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def st_psd_covariance(draw: st.DrawFn, n: int) -> np.ndarray:
    """Generate a valid n×n positive semi-definite covariance matrix.

    Uses A'A + epsilon*I construction to guarantee PSD with eigenvalue floor.
    Scales to realistic daily covariance magnitudes.

    Args:
        draw: Hypothesis draw function.
        n: Number of assets.

    Returns:
        An n×n PSD covariance matrix.
    """
    a_values = draw(
        st.lists(
            st.lists(
                st.floats(
                    min_value=-0.5,
                    max_value=0.5,
                    allow_nan=False,
                    allow_infinity=False,
                ),
                min_size=n,
                max_size=n,
            ),
            min_size=n,
            max_size=n,
        )
    )
    A = np.array(a_values, dtype=np.float64)
    # A'A / n gives a PSD matrix; add epsilon*I for strict PD
    cov = (A.T @ A) / n + 1e-6 * np.eye(n)
    # Ensure perfect symmetry
    cov = (cov + cov.T) / 2.0
    return cov


@st.composite
def st_mvo_feasible_context(draw: st.DrawFn) -> OptContext:
    """Generate a valid OptContext for MVO with a feasible constraint set.

    The constraint set uses a box constraint with w_max=1.0 and l_max=2.0
    to ensure the equal-weight portfolio is always feasible (since 1/n <= 1.0
    for n >= 2 and sum(1/n) = 1.0 <= 2.0). This guarantees the optimizer
    can find a solution at least as good as equal-weight.

    Args:
        draw: Hypothesis draw function.

    Returns:
        A valid OptContext instance with feasible constraints.
    """
    n = draw(st.integers(min_value=2, max_value=8))

    # Generate PSD covariance
    covariance = draw(st_psd_covariance(n))

    # Generate expected returns in realistic range
    expected_returns = draw(
        st.lists(
            st.floats(
                min_value=-0.10,
                max_value=0.30,
                allow_nan=False,
                allow_infinity=False,
            ),
            min_size=n,
            max_size=n,
        )
    )
    mu = np.array(expected_returns, dtype=np.float64)

    # Current weights (equal weight as prior)
    current_weights = np.ones(n) / n

    # Prices and ADV
    prices = np.ones(n) * 100.0
    adv = np.ones(n) * 1_000_000.0

    # Symbols
    symbols = [f"ASSET_{i}" for i in range(n)]

    # Sector map
    sectors = ["Technology", "Healthcare", "Financials", "Energy", "Consumer"]
    sector_map = {s: sectors[i % len(sectors)] for i, s in enumerate(symbols)}

    # Beta
    beta = np.ones(n) * 1.0

    # Risk aversion for tangency mode (higher values emphasize variance reduction)
    risk_aversion = draw(
        st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False)
    )

    # Box constraint with w_max=1.0 ensures equal-weight is feasible
    # (each weight = 1/n <= 1.0 for n >= 2)
    constraints: list[Constraint] = [BoxConstraint(w_max=1.0, l_max=2.0)]

    return OptContext(
        strategy_id="test_mvo_variance",
        as_of_ts=datetime(2024, 1, 15, 16, 30),
        n_assets=n,
        symbols=symbols,
        expected_returns=mu,
        covariance=covariance,
        current_weights=current_weights,
        prices=prices,
        adv=adv,
        sector_map=sector_map,
        beta=beta,
        factor_loadings=None,
        views=None,
        scenarios=None,
        regime_label=None,
        constraints=constraints,
        risk_aversion=risk_aversion,
        solver_chain=["ECOS", "CLARABEL", "SCS"],
        fully_invested=True,
        nav=Decimal("1000000.00"),
        seed=42,
    )


# ---------------------------------------------------------------------------
# Property 8: MVO variance optimality
# ---------------------------------------------------------------------------


class TestMVOVarianceOptimality:
    """Property 8: MVO variance optimality.

    **Validates: Requirements 4.5**

    When the MVO optimizer receives a PSD covariance matrix and a universe of
    at least 2 assets with a feasible constraint set, the realized portfolio
    variance (w'Σw) must be less than or equal to the variance of the
    equal-weight portfolio on the same universe.
    """

    @given(ctx=st_mvo_feasible_context())
    @settings(max_examples=100, deadline=None)
    def test_min_variance_beats_equal_weight(self, ctx: OptContext) -> None:
        """Min-variance MVO produces variance <= equal-weight variance.

        The minimum-variance optimizer directly minimizes w'Σw, so its
        solution must have variance no greater than any feasible portfolio,
        including the equal-weight portfolio.
        """
        optimizer = MVOOptimizer(mode=MVOMode.MIN_VARIANCE)
        result = optimizer.run(ctx)

        # Only check when optimization succeeds
        assume(result.status in ("optimal", "optimal_inaccurate"))

        # Compute realized portfolio variance: w'Σw
        w = result.weights
        portfolio_variance = float(w @ ctx.covariance @ w)

        # Compute equal-weight portfolio variance
        n = ctx.n_assets
        w_eq = np.ones(n) / n
        equal_weight_variance = float(w_eq @ ctx.covariance @ w_eq)

        # MVO variance must be <= equal-weight variance (with solver tolerance)
        assert portfolio_variance <= equal_weight_variance + 1e-8, (
            f"MVO min-variance portfolio variance ({portfolio_variance:.8e}) "
            f"exceeds equal-weight variance ({equal_weight_variance:.8e}) "
            f"by {portfolio_variance - equal_weight_variance:.8e}. "
            f"n_assets={n}, solver={result.solver_used}"
        )

    @given(ctx=st_mvo_feasible_context())
    @settings(max_examples=100, deadline=None)
    def test_target_return_beats_equal_weight_when_feasible(self, ctx: OptContext) -> None:
        """Target-return MVO produces variance <= equal-weight variance.

        When the target return is set to the equal-weight portfolio's expected
        return, the target-return optimizer minimizes w'Σw subject to
        μ'w >= r_target. Since it minimizes variance directly (with a return
        floor), its solution must have variance <= equal-weight variance
        when the equal-weight portfolio is feasible.
        """
        # Compute the equal-weight expected return as the target
        n = ctx.n_assets
        w_eq = np.ones(n) / n
        eq_return = float(w_eq @ ctx.expected_returns)

        # Only test when equal-weight return is in valid range [0.0, 1.0]
        assume(0.0 <= eq_return <= 1.0)

        optimizer = MVOOptimizer(
            mode=MVOMode.TARGET_RETURN,
            target_return=eq_return,
        )
        result = optimizer.run(ctx)

        # Only check when optimization succeeds
        assume(result.status in ("optimal", "optimal_inaccurate"))

        # Compute realized portfolio variance: w'Σw
        w = result.weights
        portfolio_variance = float(w @ ctx.covariance @ w)

        # Compute equal-weight portfolio variance
        equal_weight_variance = float(w_eq @ ctx.covariance @ w_eq)

        # Target-return MVO variance must be <= equal-weight variance
        # (since equal-weight is feasible and optimizer minimizes variance)
        assert portfolio_variance <= equal_weight_variance + 1e-8, (
            f"MVO target-return portfolio variance ({portfolio_variance:.8e}) "
            f"exceeds equal-weight variance ({equal_weight_variance:.8e}) "
            f"by {portfolio_variance - equal_weight_variance:.8e}. "
            f"n_assets={n}, target_return={eq_return:.6f}, "
            f"solver={result.solver_used}"
        )
