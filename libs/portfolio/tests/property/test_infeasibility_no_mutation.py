"""Property test for infeasibility never silently mutates.

**Validates: Requirements 2.11, 3.5**

Property 7: For ANY optimization problem that remains infeasible after all
relaxable constraints are removed, the optimizer SHALL return a failed OptResult
with an empty weight vector without raising an exception and without producing
any portfolio weights.

Strategy:
- Generate OptContext instances with contradictory non-relaxable constraints
  (priority 0, relaxable=False) that make the problem inherently infeasible.
- Optionally include relaxable constraints that will be dropped during fallback.
- Verify the optimizer returns gracefully (no exception raised).
- Verify the result has status 'failed'.
- Verify the weights array is empty (length 0).
- Verify no weights are produced that violate the non-relaxable constraints.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import cvxpy as cp
import numpy as np
import hypothesis.strategies as st
from hypothesis import given, settings, assume

from astraeus_portfolio.constraints.base import Constraint
from astraeus_portfolio.contracts import OptContext, OptResult
from astraeus_portfolio.optimizers.base import Optimizer, OptimizerConfig


# ---------------------------------------------------------------------------
# Test Optimizer (minimal concrete implementation for testing)
# ---------------------------------------------------------------------------


class MinVarianceTestOptimizer(Optimizer):
    """Minimal min-variance optimizer for testing the base class infeasibility logic."""

    def build_objective(self, w: cp.Variable, ctx: OptContext) -> cp.Expression:
        """Minimize portfolio variance: w' * Sigma * w."""
        return cp.quad_form(w, cp.psd_wrap(ctx.covariance))


# ---------------------------------------------------------------------------
# Test Constraints (non-relaxable, contradictory)
# ---------------------------------------------------------------------------


class MinWeightConstraint(Constraint):
    """Enforce w_i >= min_weight for all assets. Priority 0, never relaxed."""

    def __init__(self, min_weight: float) -> None:
        super().__init__(name="min_weight", priority=0, relaxable=False)
        self.min_weight = min_weight

    def to_cvxpy(self, w: cp.Variable, ctx: OptContext) -> list:
        return [w >= self.min_weight]

    def diagnostic(self, w_value: np.ndarray, ctx: OptContext) -> dict:
        min_val = float(np.min(w_value)) if len(w_value) > 0 else 0.0
        return {"satisfied": min_val >= self.min_weight - 1e-8, "min_weight": min_val}


class MaxWeightConstraint(Constraint):
    """Enforce w_i <= max_weight for all assets. Priority 0, never relaxed."""

    def __init__(self, max_weight: float) -> None:
        super().__init__(name="max_weight", priority=0, relaxable=False)
        self.max_weight = max_weight

    def to_cvxpy(self, w: cp.Variable, ctx: OptContext) -> list:
        return [w <= self.max_weight]

    def diagnostic(self, w_value: np.ndarray, ctx: OptContext) -> dict:
        max_val = float(np.max(w_value)) if len(w_value) > 0 else 0.0
        return {"satisfied": max_val <= self.max_weight + 1e-8, "max_weight": max_val}


class SumCapConstraint(Constraint):
    """Enforce sum(w) <= cap. Priority 0, never relaxed.

    Used to contradict the fully_invested constraint (sum(w) == 1).
    """

    def __init__(self, cap: float) -> None:
        super().__init__(name="sum_cap", priority=0, relaxable=False)
        self.cap = cap

    def to_cvxpy(self, w: cp.Variable, ctx: OptContext) -> list:
        return [cp.sum(w) <= self.cap]

    def diagnostic(self, w_value: np.ndarray, ctx: OptContext) -> dict:
        total = float(np.sum(w_value)) if len(w_value) > 0 else 0.0
        return {"satisfied": total <= self.cap + 1e-8, "sum": total}


class RelaxableDummyConstraint(Constraint):
    """A relaxable constraint that is always satisfiable (used to test relaxation path)."""

    def __init__(self, priority: int = 2) -> None:
        super().__init__(name=f"relaxable_dummy_p{priority}", priority=priority, relaxable=True)

    def to_cvxpy(self, w: cp.Variable, ctx: OptContext) -> list:
        # Always satisfiable: sum of absolute weights <= 100
        return [cp.norm(w, 1) <= 100.0]

    def diagnostic(self, w_value: np.ndarray, ctx: OptContext) -> dict:
        return {"satisfied": True, "norm_1": float(np.sum(np.abs(w_value)))}


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------


def _make_psd_matrix(n: int, rng: np.random.Generator) -> np.ndarray:
    """Generate a random positive semi-definite matrix of shape (n, n)."""
    A = rng.standard_normal((n, n))
    return A.T @ A + 1e-6 * np.eye(n)


@st.composite
def st_infeasible_opt_context(draw: st.DrawFn) -> OptContext:
    """Generate an OptContext with contradictory non-relaxable constraints.

    The infeasibility is created by combining:
    - fully_invested=True (sum(w) == 1)
    - A MaxWeightConstraint with max_weight < 1/n (impossible to sum to 1)

    This guarantees the problem is infeasible regardless of relaxable constraints.
    """
    n = draw(st.integers(min_value=2, max_value=8))
    seed = draw(st.integers(min_value=0, max_value=2**31 - 1))
    rng = np.random.default_rng(seed)

    # Create a valid PSD covariance matrix
    covariance = _make_psd_matrix(n, rng)

    # Expected returns
    expected_returns = rng.standard_normal(n) * 0.01

    # Current weights (equal weight)
    current_weights = np.ones(n) / n

    # Prices and ADV
    prices = rng.uniform(10.0, 500.0, size=n)
    adv = rng.uniform(100_000, 10_000_000, size=n)

    # Betas
    beta = rng.uniform(0.5, 1.5, size=n)

    # Symbols and sector map
    symbols = [f"ASSET_{i}" for i in range(n)]
    sector_map = {s: "Technology" for s in symbols}

    # --- Create contradictory non-relaxable constraints ---
    # With fully_invested=True, sum(w) == 1.
    # Set max_weight < 1/n so that n * max_weight < 1, making sum(w) == 1 impossible.
    # Choose max_weight in (0, 1/n) exclusive
    max_weight_upper = 1.0 / n
    max_weight = draw(
        st.floats(min_value=0.01, max_value=max_weight_upper * 0.9, allow_nan=False, allow_infinity=False)
    )
    non_relaxable_constraints: list[Constraint] = [
        MaxWeightConstraint(max_weight=max_weight),
    ]

    # Optionally add relaxable constraints to exercise the relaxation path
    n_relaxable = draw(st.integers(min_value=0, max_value=3))
    relaxable_constraints: list[Constraint] = []
    for i in range(n_relaxable):
        priority = draw(st.sampled_from([1, 2, 3]))
        relaxable_constraints.append(RelaxableDummyConstraint(priority=priority))

    all_constraints = non_relaxable_constraints + relaxable_constraints

    return OptContext(
        strategy_id="test_infeasible",
        as_of_ts=datetime(2024, 1, 15, tzinfo=timezone.utc),
        n_assets=n,
        symbols=symbols,
        expected_returns=expected_returns,
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
        constraints=all_constraints,
        risk_aversion=5.0,
        solver_chain=["ECOS", "CLARABEL", "SCS"],
        fully_invested=True,
        nav=Decimal("1000000.00"),
        seed=seed,
    )


@st.composite
def st_infeasible_sum_cap_context(draw: st.DrawFn) -> OptContext:
    """Generate an OptContext with a sum-cap constraint contradicting fully_invested.

    The infeasibility is created by:
    - fully_invested=True (sum(w) == 1)
    - A SumCapConstraint with cap < 1 (sum(w) <= cap < 1, contradicts sum(w) == 1)
    - A MinWeightConstraint with min_weight >= 0 (non-negative weights)
    """
    n = draw(st.integers(min_value=2, max_value=8))
    seed = draw(st.integers(min_value=0, max_value=2**31 - 1))
    rng = np.random.default_rng(seed)

    covariance = _make_psd_matrix(n, rng)
    expected_returns = rng.standard_normal(n) * 0.01
    current_weights = np.ones(n) / n
    prices = rng.uniform(10.0, 500.0, size=n)
    adv = rng.uniform(100_000, 10_000_000, size=n)
    beta = rng.uniform(0.5, 1.5, size=n)
    symbols = [f"ASSET_{i}" for i in range(n)]
    sector_map = {s: "Financials" for s in symbols}

    # sum(w) <= cap where cap < 1, contradicts sum(w) == 1
    cap = draw(st.floats(min_value=0.01, max_value=0.8, allow_nan=False, allow_infinity=False))

    non_relaxable_constraints: list[Constraint] = [
        SumCapConstraint(cap=cap),
        MinWeightConstraint(min_weight=0.0),
    ]

    # Optionally add relaxable constraints
    n_relaxable = draw(st.integers(min_value=0, max_value=2))
    relaxable_constraints: list[Constraint] = [
        RelaxableDummyConstraint(priority=p)
        for p in [2, 3][:n_relaxable]
    ]

    all_constraints = non_relaxable_constraints + relaxable_constraints

    return OptContext(
        strategy_id="test_infeasible_sum_cap",
        as_of_ts=datetime(2024, 1, 15, tzinfo=timezone.utc),
        n_assets=n,
        symbols=symbols,
        expected_returns=expected_returns,
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
        constraints=all_constraints,
        risk_aversion=5.0,
        solver_chain=["ECOS", "CLARABEL", "SCS"],
        fully_invested=True,
        nav=Decimal("1000000.00"),
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Property 7: Infeasibility never silently mutates
# ---------------------------------------------------------------------------


class TestInfeasibilityNeverSilentlyMutates:
    """Property 7: Infeasibility never silently mutates.

    **Validates: Requirements 2.11, 3.5**

    When all relaxable constraints have been removed and the problem remains
    infeasible, the optimizer must return a failed OptResult with empty weights.
    It must never silently adjust or mutate the portfolio to make it pass.
    """

    @given(ctx=st_infeasible_opt_context())
    @settings(max_examples=50, deadline=None)
    def test_returns_failed_status_on_infeasible_max_weight(self, ctx: OptContext) -> None:
        """Optimizer returns 'failed' status when max_weight makes sum(w)==1 impossible."""
        optimizer = MinVarianceTestOptimizer(OptimizerConfig())

        # Must not raise an exception
        result = optimizer.run(ctx)

        assert result.status == "failed", (
            f"Expected status 'failed', got '{result.status}'. "
            f"Weights: {result.weights}"
        )

    @given(ctx=st_infeasible_opt_context())
    @settings(max_examples=50, deadline=None)
    def test_returns_empty_weights_on_infeasible_max_weight(self, ctx: OptContext) -> None:
        """Optimizer returns empty weight vector when problem is infeasible."""
        optimizer = MinVarianceTestOptimizer(OptimizerConfig())

        result = optimizer.run(ctx)

        assert len(result.weights) == 0, (
            f"Expected empty weights, got array of length {len(result.weights)}: "
            f"{result.weights}"
        )

    @given(ctx=st_infeasible_opt_context())
    @settings(max_examples=50, deadline=None)
    def test_no_exception_raised_on_infeasible_max_weight(self, ctx: OptContext) -> None:
        """Optimizer does not raise an exception on infeasible problems."""
        optimizer = MinVarianceTestOptimizer(OptimizerConfig())

        # This should complete without raising any exception
        try:
            result = optimizer.run(ctx)
        except Exception as e:
            raise AssertionError(
                f"Optimizer raised {type(e).__name__}: {e}. "
                "Expected graceful return of failed OptResult."
            )

        # Verify it's a valid OptResult
        assert isinstance(result, OptResult)

    @given(ctx=st_infeasible_sum_cap_context())
    @settings(max_examples=50, deadline=None)
    def test_returns_failed_status_on_infeasible_sum_cap(self, ctx: OptContext) -> None:
        """Optimizer returns 'failed' when sum-cap contradicts fully_invested."""
        optimizer = MinVarianceTestOptimizer(OptimizerConfig())

        result = optimizer.run(ctx)

        assert result.status == "failed", (
            f"Expected status 'failed', got '{result.status}'. "
            f"Weights: {result.weights}"
        )

    @given(ctx=st_infeasible_sum_cap_context())
    @settings(max_examples=50, deadline=None)
    def test_returns_empty_weights_on_infeasible_sum_cap(self, ctx: OptContext) -> None:
        """Optimizer returns empty weight vector when sum-cap makes problem infeasible."""
        optimizer = MinVarianceTestOptimizer(OptimizerConfig())

        result = optimizer.run(ctx)

        assert len(result.weights) == 0, (
            f"Expected empty weights, got array of length {len(result.weights)}: "
            f"{result.weights}"
        )

    @given(ctx=st_infeasible_opt_context())
    @settings(max_examples=50, deadline=None)
    def test_solver_used_is_none_on_infeasible(self, ctx: OptContext) -> None:
        """Optimizer reports no solver used when problem is infeasible."""
        optimizer = MinVarianceTestOptimizer(OptimizerConfig())

        result = optimizer.run(ctx)

        assert result.solver_used is None, (
            f"Expected solver_used=None, got '{result.solver_used}'"
        )

    @given(ctx=st_infeasible_opt_context())
    @settings(max_examples=50, deadline=None)
    def test_relaxation_events_emitted_when_relaxable_present(self, ctx: OptContext) -> None:
        """Optimizer emits relaxation events for each dropped relaxable constraint."""
        optimizer = MinVarianceTestOptimizer(OptimizerConfig())

        result = optimizer.run(ctx)

        # Count relaxable constraints in the context
        n_relaxable = sum(1 for c in ctx.constraints if c.relaxable)

        # Should have one relaxation event per relaxable constraint dropped
        assert len(result.relaxation_events) == n_relaxable, (
            f"Expected {n_relaxable} relaxation events, "
            f"got {len(result.relaxation_events)}"
        )
