"""Property test for constraint relaxation ordering.

**Validates: Requirements 2.10, 3.4, 3.6**

Property 6: Constraint relaxation ordering — When the optimizer encounters
infeasibility and relaxes constraints, it must drop them in descending priority
order (highest priority first). Priority 0 constraints are never relaxed.
RelaxationEvents must be emitted in order with correct iteration counts.

This test generates scenarios with multiple constraints at different priorities
that create infeasibility, then verifies:
1. Relaxation events are emitted in descending priority order (highest first)
2. Priority 0 constraints are never dropped
3. Iteration counts are 1-indexed and sequential
4. Each relaxation event contains the correct constraint name and priority
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import cvxpy as cp
import hypothesis.strategies as st
import numpy as np
from astraeus_portfolio.constraints.base import Constraint, relax_constraints
from astraeus_portfolio.contracts import OptContext, RelaxationEvent
from astraeus_portfolio.optimizers.base import Optimizer, OptimizerConfig
from hypothesis import assume, given, settings

# ---------------------------------------------------------------------------
# Test Helpers: Concrete constraint and optimizer for testing
# ---------------------------------------------------------------------------


class _InfeasibleConstraint(Constraint):
    """A constraint that is always infeasible (forces relaxation).

    Used to create scenarios where the optimizer must relax constraints.
    """

    def __init__(self, name: str, priority: int, relaxable: bool) -> None:
        super().__init__(name=name, priority=priority, relaxable=relaxable)

    def to_cvxpy(self, w: cp.Variable, ctx: Any) -> list[cp.constraints.constraint.Constraint]:
        """Return a constraint that is impossible to satisfy with sum(w)=1.

        Forces sum(w) >= 2, which contradicts the fully-invested sum(w)=1.
        """
        return [cp.sum(w) >= 2.0]

    def diagnostic(self, w_value: np.ndarray, ctx: Any) -> dict:
        return {"satisfied": False, "reason": "always_infeasible"}


class _FeasibleConstraint(Constraint):
    """A constraint that is always feasible (never blocks optimization).

    Used as a priority-0 non-relaxable constraint that doesn't interfere.
    """

    def __init__(self, name: str, priority: int, relaxable: bool) -> None:
        super().__init__(name=name, priority=priority, relaxable=relaxable)

    def to_cvxpy(self, w: cp.Variable, ctx: Any) -> list[cp.constraints.constraint.Constraint]:
        """Return a trivially satisfiable constraint (w >= -100)."""
        return [w >= -100.0]

    def diagnostic(self, w_value: np.ndarray, ctx: Any) -> dict:
        return {"satisfied": True}


class _SimpleMinVarianceOptimizer(Optimizer):
    """A minimal optimizer for testing: minimizes w'Σw."""

    def build_objective(self, w: cp.Variable, ctx: OptContext) -> cp.Expression:
        return cp.quad_form(w, cp.psd_wrap(ctx.covariance))


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def st_constraint_priorities(draw: st.DrawFn) -> list[tuple[str, int, bool]]:
    """Generate a list of constraint specs with varied priorities.

    Returns a list of (name, priority, relaxable) tuples where:
    - At least one priority-0 non-relaxable constraint exists
    - At least two relaxable constraints with priority > 0 exist
    - Priorities range from 0 to 5
    - Names are unique

    This ensures we have a meaningful relaxation ordering to test.
    """
    # Always include at least one priority-0 non-relaxable constraint
    n_non_relaxable = draw(st.integers(min_value=1, max_value=3))
    non_relaxable = [(f"fixed_{i}", 0, False) for i in range(n_non_relaxable)]

    # Generate relaxable constraints with priorities 1-5
    n_relaxable = draw(st.integers(min_value=2, max_value=6))
    relaxable = []
    for i in range(n_relaxable):
        priority = draw(st.integers(min_value=1, max_value=5))
        relaxable.append((f"relaxable_{i}", priority, True))

    return non_relaxable + relaxable


@st.composite
def st_infeasible_opt_context(draw: st.DrawFn) -> tuple[OptContext, list[Constraint]]:
    """Generate an OptContext with constraints that create infeasibility.

    Creates a scenario where:
    - The problem is infeasible with all constraints active
    - Priority-0 constraints are feasible on their own
    - Relaxable constraints (priority > 0) are infeasible

    Returns:
        Tuple of (OptContext, list of all constraints including infeasible ones)
    """
    n_assets = draw(st.integers(min_value=2, max_value=5))

    # Generate a valid PSD covariance matrix
    A = np.random.default_rng(42).standard_normal((n_assets, n_assets))
    cov = A.T @ A + 1e-4 * np.eye(n_assets)

    # Generate constraint specs
    constraint_specs = draw(st_constraint_priorities())

    # Build constraint objects:
    # - Priority 0 constraints are feasible (don't block optimization)
    # - Relaxable constraints are infeasible (force relaxation)
    constraints: list[Constraint] = []
    for name, priority, relaxable in constraint_specs:
        if priority == 0:
            constraints.append(
                _FeasibleConstraint(name=name, priority=priority, relaxable=relaxable)
            )
        else:
            constraints.append(
                _InfeasibleConstraint(name=name, priority=priority, relaxable=relaxable)
            )

    ctx = OptContext(
        strategy_id="test_strategy",
        as_of_ts=datetime(2024, 1, 15, 16, 30),
        n_assets=n_assets,
        symbols=[f"SYM{i}" for i in range(n_assets)],
        expected_returns=np.ones(n_assets) * 0.05,
        covariance=cov,
        current_weights=np.ones(n_assets) / n_assets,
        prices=np.ones(n_assets) * 100.0,
        adv=np.ones(n_assets) * 1_000_000.0,
        sector_map={f"SYM{i}": "Technology" for i in range(n_assets)},
        beta=np.ones(n_assets) * 1.0,
        factor_loadings=None,
        views=None,
        scenarios=None,
        regime_label=None,
        constraints=constraints,
        risk_aversion=5.0,
        solver_chain=["ECOS", "CLARABEL", "SCS"],
        fully_invested=True,
        nav=Decimal("1000000"),
        seed=42,
    )

    return ctx, constraints


# ---------------------------------------------------------------------------
# Property 6: Constraint relaxation ordering
# ---------------------------------------------------------------------------


class TestConstraintRelaxationOrdering:
    """Property 6: Constraint relaxation ordering.

    **Validates: Requirements 2.10, 3.4, 3.6**

    When the optimizer encounters infeasibility and relaxes constraints,
    it must drop them in descending priority order (highest priority first).
    Priority 0 constraints are never relaxed. RelaxationEvents must be
    emitted in order with correct iteration counts.
    """

    @given(constraint_specs=st_constraint_priorities())
    @settings(max_examples=200, deadline=None)
    def test_relaxation_order_descending_priority(
        self, constraint_specs: list[tuple[str, int, bool]]
    ) -> None:
        """Relaxable constraints are yielded in descending priority order.

        The `relax_constraints` function must drop constraints with the
        highest priority first (descending order).
        """
        constraints = []
        for name, priority, relaxable in constraint_specs:
            if priority == 0:
                constraints.append(
                    _FeasibleConstraint(name=name, priority=priority, relaxable=relaxable)
                )
            else:
                constraints.append(
                    _InfeasibleConstraint(name=name, priority=priority, relaxable=relaxable)
                )

        events: list[RelaxationEvent] = []
        for _remaining, event in relax_constraints(constraints):
            events.append(event)

        # Verify events are in descending priority order
        if len(events) >= 2:
            for i in range(len(events) - 1):
                assert events[i].priority >= events[i + 1].priority, (
                    f"Relaxation event at iteration {events[i].iteration} has priority "
                    f"{events[i].priority} but next event at iteration {events[i + 1].iteration} "
                    f"has higher priority {events[i + 1].priority}. "
                    f"Constraints must be relaxed in descending priority order."
                )

    @given(constraint_specs=st_constraint_priorities())
    @settings(max_examples=200, deadline=None)
    def test_priority_zero_never_relaxed(
        self, constraint_specs: list[tuple[str, int, bool]]
    ) -> None:
        """Priority 0 constraints are never included in relaxation events."""
        constraints = []
        for name, priority, relaxable in constraint_specs:
            if priority == 0:
                constraints.append(
                    _FeasibleConstraint(name=name, priority=priority, relaxable=relaxable)
                )
            else:
                constraints.append(
                    _InfeasibleConstraint(name=name, priority=priority, relaxable=relaxable)
                )

        for _remaining, event in relax_constraints(constraints):
            assert event.priority > 0, (
                f"Priority 0 constraint '{event.constraint_name}' was relaxed at "
                f"iteration {event.iteration}. Priority 0 constraints must NEVER be relaxed."
            )

    @given(constraint_specs=st_constraint_priorities())
    @settings(max_examples=200, deadline=None)
    def test_iteration_counts_sequential_one_indexed(
        self, constraint_specs: list[tuple[str, int, bool]]
    ) -> None:
        """RelaxationEvent iteration counts are 1-indexed and sequential."""
        constraints = []
        for name, priority, relaxable in constraint_specs:
            if priority == 0:
                constraints.append(
                    _FeasibleConstraint(name=name, priority=priority, relaxable=relaxable)
                )
            else:
                constraints.append(
                    _InfeasibleConstraint(name=name, priority=priority, relaxable=relaxable)
                )

        events: list[RelaxationEvent] = []
        for _remaining, event in relax_constraints(constraints):
            events.append(event)

        # Verify 1-indexed sequential iteration counts
        for i, event in enumerate(events):
            expected_iteration = i + 1
            assert event.iteration == expected_iteration, (
                f"Event for '{event.constraint_name}' has iteration={event.iteration}, "
                f"expected {expected_iteration}. Iterations must be 1-indexed and sequential."
            )

    @given(constraint_specs=st_constraint_priorities())
    @settings(max_examples=200, deadline=None)
    def test_relaxation_events_match_relaxable_constraints(
        self, constraint_specs: list[tuple[str, int, bool]]
    ) -> None:
        """Number of relaxation events equals number of relaxable constraints."""
        constraints = []
        relaxable_names = set()
        for name, priority, relaxable in constraint_specs:
            if priority == 0:
                constraints.append(
                    _FeasibleConstraint(name=name, priority=priority, relaxable=relaxable)
                )
            else:
                constraints.append(
                    _InfeasibleConstraint(name=name, priority=priority, relaxable=relaxable)
                )
                relaxable_names.add(name)

        events: list[RelaxationEvent] = []
        for _remaining, event in relax_constraints(constraints):
            events.append(event)

        # Every relaxable constraint should appear exactly once in events
        event_names = {e.constraint_name for e in events}
        assert event_names == relaxable_names, (
            f"Relaxation events don't match relaxable constraints. "
            f"Events: {event_names}, Expected: {relaxable_names}"
        )

    @given(constraint_specs=st_constraint_priorities())
    @settings(max_examples=200, deadline=None)
    def test_remaining_constraints_shrink_monotonically(
        self, constraint_specs: list[tuple[str, int, bool]]
    ) -> None:
        """Each relaxation step removes exactly one constraint from remaining."""
        constraints = []
        for name, priority, relaxable in constraint_specs:
            if priority == 0:
                constraints.append(
                    _FeasibleConstraint(name=name, priority=priority, relaxable=relaxable)
                )
            else:
                constraints.append(
                    _InfeasibleConstraint(name=name, priority=priority, relaxable=relaxable)
                )

        total_count = len(constraints)
        prev_count = total_count

        for remaining, event in relax_constraints(constraints):
            current_count = len(remaining)
            assert current_count == prev_count - 1, (
                f"After relaxing '{event.constraint_name}', expected "
                f"{prev_count - 1} remaining constraints but got {current_count}."
            )
            prev_count = current_count

    @given(data=st_infeasible_opt_context())
    @settings(max_examples=50, deadline=None)
    def test_optimizer_relaxation_events_ordering(
        self, data: tuple[OptContext, list[Constraint]]
    ) -> None:
        """Optimizer emits relaxation events in descending priority order.

        End-to-end test: run the optimizer with an infeasible constraint set
        and verify the resulting OptResult contains properly ordered
        RelaxationEvents.
        """
        ctx, constraints = data

        # Ensure we have relaxable constraints to test
        relaxable = [c for c in constraints if c.relaxable and c.priority > 0]
        assume(len(relaxable) >= 2)

        optimizer = _SimpleMinVarianceOptimizer(
            config=OptimizerConfig(solver_chain=["ECOS", "CLARABEL", "SCS"])
        )
        result = optimizer.run(ctx)

        # The optimizer should have attempted relaxation
        if result.relaxation_events:
            # Verify descending priority order
            for i in range(len(result.relaxation_events) - 1):
                assert (
                    result.relaxation_events[i].priority >= result.relaxation_events[i + 1].priority
                ), (
                    f"Optimizer relaxation event at iteration "
                    f"{result.relaxation_events[i].iteration} has priority "
                    f"{result.relaxation_events[i].priority} but next event has "
                    f"higher priority {result.relaxation_events[i + 1].priority}."
                )

            # Verify no priority-0 constraints were relaxed
            for event in result.relaxation_events:
                assert event.priority > 0, (
                    f"Optimizer relaxed priority-0 constraint '{event.constraint_name}'. "
                    f"Priority 0 constraints must NEVER be relaxed."
                )

            # Verify 1-indexed sequential iterations
            for i, event in enumerate(result.relaxation_events):
                assert event.iteration == i + 1, (
                    f"Optimizer relaxation event for '{event.constraint_name}' has "
                    f"iteration={event.iteration}, expected {i + 1}."
                )

    @given(data=st_infeasible_opt_context())
    @settings(max_examples=50, deadline=None)
    def test_optimizer_priority_zero_preserved_in_result(
        self, data: tuple[OptContext, list[Constraint]]
    ) -> None:
        """Priority 0 constraints are never present in optimizer relaxation events.

        Even when the optimizer exhausts all relaxable constraints, priority 0
        constraints must remain intact and never appear in relaxation events.
        """
        ctx, constraints = data

        optimizer = _SimpleMinVarianceOptimizer(
            config=OptimizerConfig(solver_chain=["ECOS", "CLARABEL", "SCS"])
        )
        result = optimizer.run(ctx)

        # Collect all priority-0 constraint names
        priority_zero_names = {c.name for c in constraints if c.priority == 0}

        # None of them should appear in relaxation events
        relaxed_names = {e.constraint_name for e in result.relaxation_events}
        violated = priority_zero_names & relaxed_names

        assert not violated, (
            f"Priority 0 constraints were relaxed: {violated}. "
            f"Priority 0 constraints must NEVER be relaxed."
        )
