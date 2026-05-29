"""Property tests for optimizer weight-sum invariant and determinism.

**Validates: Requirements 3.7, 3.8**

Property 4: Optimizer weight-sum invariant
    For any feasible OptContext with fully_invested=True, the optimizer SHALL
    produce weights that sum to 1.0 within a tolerance of 1e-6. For
    fully_invested=False (net-zero), weights SHALL sum to 0.0 within 1e-6.

Property 5: Optimizer determinism
    For any OptContext, running the same optimizer twice on the same machine
    with the same configuration SHALL produce weight vectors that are identical
    within 1e-10 tolerance.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import numpy as np
import hypothesis.strategies as st
from hypothesis import given, settings, assume

from astraeus_portfolio.constraints.base import Constraint
from astraeus_portfolio.constraints.box import BoxConstraint
from astraeus_portfolio.contracts import OptContext
from astraeus_portfolio.optimizers.base import OptimizerConfig
from astraeus_portfolio.optimizers.mvo import MVOMode, MVOOptimizer


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def st_psd_covariance(draw: st.DrawFn, n: int) -> np.ndarray:
    """Generate a valid n×n positive semi-definite covariance matrix.

    Uses A'A + epsilon*I construction to guarantee PSD with eigenvalue floor.

    Args:
        draw: Hypothesis draw function.
        n: Number of assets.

    Returns:
        An n×n PSD covariance matrix with realistic magnitudes.
    """
    # Generate a random matrix and form A'A to ensure PSD
    a_values = draw(
        st.lists(
            st.lists(
                st.floats(
                    min_value=-0.5, max_value=0.5,
                    allow_nan=False, allow_infinity=False,
                ),
                min_size=n,
                max_size=n,
            ),
            min_size=n,
            max_size=n,
        )
    )
    A = np.array(a_values, dtype=np.float64)
    # Scale to realistic daily covariance magnitudes
    cov = (A.T @ A) / n + 1e-6 * np.eye(n)
    # Ensure perfect symmetry
    cov = (cov + cov.T) / 2.0
    return cov


@st.composite
def st_opt_context(
    draw: st.DrawFn,
    fully_invested: bool = True,
) -> OptContext:
    """Generate a valid OptContext for MVO optimization.

    Produces a feasible optimization problem with:
    - 2-8 assets
    - PSD covariance matrix
    - Realistic expected returns
    - Box constraint with w_max large enough to allow feasibility

    Args:
        draw: Hypothesis draw function.
        fully_invested: Whether sum(w) = 1 (True) or sum(w) = 0 (False).

    Returns:
        A valid OptContext instance.
    """
    n = draw(st.integers(min_value=2, max_value=8))

    # Generate PSD covariance
    covariance = draw(st_psd_covariance(n))

    # Generate expected returns in realistic range
    expected_returns = draw(
        st.lists(
            st.floats(
                min_value=-0.10, max_value=0.30,
                allow_nan=False, allow_infinity=False,
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

    # Risk aversion
    risk_aversion = draw(
        st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False)
    )

    # Box constraint with w_max = 1.0 to ensure feasibility for fully_invested
    # (each asset can hold up to 100%, so sum=1 is always feasible)
    constraints: list[Constraint] = [BoxConstraint(w_max=1.0, l_max=2.0)]

    return OptContext(
        strategy_id="test_strategy",
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
        fully_invested=fully_invested,
        nav=Decimal("1000000.00"),
        seed=42,
    )


@st.composite
def st_opt_context_net_zero(draw: st.DrawFn) -> OptContext:
    """Generate a valid OptContext for net-zero (market-neutral) optimization.

    For net-zero mode, we relax the box constraint to allow negative weights
    (long-short) so that sum(w) = 0 is feasible.

    Args:
        draw: Hypothesis draw function.

    Returns:
        A valid OptContext with fully_invested=False.
    """
    n = draw(st.integers(min_value=2, max_value=8))

    # Generate PSD covariance
    covariance = draw(st_psd_covariance(n))

    # Generate expected returns
    expected_returns = draw(
        st.lists(
            st.floats(
                min_value=-0.10, max_value=0.30,
                allow_nan=False, allow_infinity=False,
            ),
            min_size=n,
            max_size=n,
        )
    )
    mu = np.array(expected_returns, dtype=np.float64)

    # Current weights
    current_weights = np.zeros(n)

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

    # Risk aversion
    risk_aversion = draw(
        st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False)
    )

    # No box constraint for net-zero (need negative weights)
    # Use a leverage constraint only
    constraints: list[Constraint] = []

    return OptContext(
        strategy_id="test_strategy_neutral",
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
        fully_invested=False,
        nav=Decimal("1000000.00"),
        seed=42,
    )


# ---------------------------------------------------------------------------
# Property 4: Optimizer weight-sum invariant
# ---------------------------------------------------------------------------


class TestOptimizerWeightSumInvariant:
    """Property 4: Optimizer weight-sum invariant.

    **Validates: Requirements 3.8**

    For any feasible OptContext with fully_invested=True, the optimizer SHALL
    produce weights that sum to 1.0 within solver tolerance (1e-6). For
    fully_invested=False (net-zero), weights SHALL sum to 0.0 within 1e-6.
    """

    @given(ctx=st_opt_context(fully_invested=True))
    @settings(max_examples=100, deadline=None)
    def test_fully_invested_weights_sum_to_one(self, ctx: OptContext) -> None:
        """Fully-invested optimizer produces weights summing to 1.0 within 1e-6."""
        optimizer = MVOOptimizer(mode=MVOMode.TANGENCY)
        result = optimizer.run(ctx)

        # Only check if optimization succeeded
        assume(result.status in ("optimal", "optimal_inaccurate"))

        weight_sum = float(np.sum(result.weights))
        assert abs(weight_sum - 1.0) <= 1e-6, (
            f"Weight sum {weight_sum} deviates from 1.0 by "
            f"{abs(weight_sum - 1.0):.2e} (tolerance: 1e-6)"
        )

    @given(ctx=st_opt_context(fully_invested=True))
    @settings(max_examples=100, deadline=None)
    def test_min_variance_weights_sum_to_one(self, ctx: OptContext) -> None:
        """Min-variance optimizer produces weights summing to 1.0 within 1e-6."""
        optimizer = MVOOptimizer(mode=MVOMode.MIN_VARIANCE)
        result = optimizer.run(ctx)

        # Only check if optimization succeeded
        assume(result.status in ("optimal", "optimal_inaccurate"))

        weight_sum = float(np.sum(result.weights))
        assert abs(weight_sum - 1.0) <= 1e-6, (
            f"Weight sum {weight_sum} deviates from 1.0 by "
            f"{abs(weight_sum - 1.0):.2e} (tolerance: 1e-6)"
        )

    @given(ctx=st_opt_context_net_zero())
    @settings(max_examples=100, deadline=None)
    def test_net_zero_weights_sum_to_zero(self, ctx: OptContext) -> None:
        """Net-zero optimizer produces weights summing to 0.0 within 1e-6."""
        optimizer = MVOOptimizer(mode=MVOMode.TANGENCY)
        result = optimizer.run(ctx)

        # Only check if optimization succeeded
        assume(result.status in ("optimal", "optimal_inaccurate"))

        weight_sum = float(np.sum(result.weights))
        assert abs(weight_sum - 0.0) <= 1e-6, (
            f"Weight sum {weight_sum} deviates from 0.0 by "
            f"{abs(weight_sum):.2e} (tolerance: 1e-6)"
        )


# ---------------------------------------------------------------------------
# Property 5: Optimizer determinism
# ---------------------------------------------------------------------------


class TestOptimizerDeterminism:
    """Property 5: Optimizer determinism.

    **Validates: Requirements 3.7**

    For any OptContext, running the same optimizer twice on the same machine
    with the same configuration SHALL produce weight vectors that are identical
    within 1e-10 tolerance.
    """

    @given(ctx=st_opt_context(fully_invested=True))
    @settings(max_examples=100, deadline=None)
    def test_tangency_determinism(self, ctx: OptContext) -> None:
        """Tangency MVO produces identical results across repeated runs."""
        config = OptimizerConfig(solver_chain=["ECOS", "CLARABEL", "SCS"])
        optimizer = MVOOptimizer(mode=MVOMode.TANGENCY, config=config)

        result1 = optimizer.run(ctx)
        result2 = optimizer.run(ctx)

        # Only check if both optimizations succeeded
        assume(result1.status in ("optimal", "optimal_inaccurate"))
        assume(result2.status in ("optimal", "optimal_inaccurate"))

        np.testing.assert_allclose(
            result1.weights,
            result2.weights,
            atol=1e-10,
            err_msg=(
                f"Optimizer produced non-deterministic results. "
                f"Max diff: {np.max(np.abs(result1.weights - result2.weights)):.2e}"
            ),
        )

    @given(ctx=st_opt_context(fully_invested=True))
    @settings(max_examples=100, deadline=None)
    def test_min_variance_determinism(self, ctx: OptContext) -> None:
        """Min-variance MVO produces identical results across repeated runs."""
        config = OptimizerConfig(solver_chain=["ECOS", "CLARABEL", "SCS"])
        optimizer = MVOOptimizer(mode=MVOMode.MIN_VARIANCE, config=config)

        result1 = optimizer.run(ctx)
        result2 = optimizer.run(ctx)

        # Only check if both optimizations succeeded
        assume(result1.status in ("optimal", "optimal_inaccurate"))
        assume(result2.status in ("optimal", "optimal_inaccurate"))

        np.testing.assert_allclose(
            result1.weights,
            result2.weights,
            atol=1e-10,
            err_msg=(
                f"Optimizer produced non-deterministic results. "
                f"Max diff: {np.max(np.abs(result1.weights - result2.weights)):.2e}"
            ),
        )

    @given(ctx=st_opt_context_net_zero())
    @settings(max_examples=100, deadline=None)
    def test_net_zero_determinism(self, ctx: OptContext) -> None:
        """Net-zero MVO produces identical results across repeated runs."""
        config = OptimizerConfig(solver_chain=["ECOS", "CLARABEL", "SCS"])
        optimizer = MVOOptimizer(mode=MVOMode.TANGENCY, config=config)

        result1 = optimizer.run(ctx)
        result2 = optimizer.run(ctx)

        # Only check if both optimizations succeeded
        assume(result1.status in ("optimal", "optimal_inaccurate"))
        assume(result2.status in ("optimal", "optimal_inaccurate"))

        np.testing.assert_allclose(
            result1.weights,
            result2.weights,
            atol=1e-10,
            err_msg=(
                f"Optimizer produced non-deterministic results. "
                f"Max diff: {np.max(np.abs(result1.weights - result2.weights)):.2e}"
            ),
        )
