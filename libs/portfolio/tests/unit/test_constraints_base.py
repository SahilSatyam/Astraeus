"""Unit tests for Constraint ABC and relaxation ordering logic."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from astraeus_portfolio.constraints.base import (
    Constraint,
    get_relaxation_order,
    relax_constraints,
)
from astraeus_portfolio.contracts import RelaxationEvent

if TYPE_CHECKING:
    import cvxpy as cp
    from astraeus_portfolio.contracts import OptContext


# ---------------------------------------------------------------------------
# Concrete test constraint for testing the ABC
# ---------------------------------------------------------------------------


class DummyConstraint(Constraint):
    """Minimal concrete constraint for testing."""

    def to_cvxpy(self, w: "cp.Variable", ctx: "OptContext") -> list:
        return []

    def diagnostic(self, w_value: np.ndarray, ctx: "OptContext") -> dict:
        return {"satisfied": True, "name": self.name}


# ---------------------------------------------------------------------------
# Tests: Constraint ABC initialization
# ---------------------------------------------------------------------------


class TestConstraintInit:
    """Tests for Constraint initialization and validation."""

    def test_valid_relaxable_constraint(self) -> None:
        c = DummyConstraint(name="turnover", priority=3, relaxable=True)
        assert c.name == "turnover"
        assert c.priority == 3
        assert c.relaxable is True

    def test_valid_non_relaxable_constraint(self) -> None:
        c = DummyConstraint(name="box", priority=0, relaxable=False)
        assert c.name == "box"
        assert c.priority == 0
        assert c.relaxable is False

    def test_priority_zero_relaxable_raises(self) -> None:
        with pytest.raises(ValueError, match="priority 0 but relaxable=True"):
            DummyConstraint(name="bad", priority=0, relaxable=True)

    def test_negative_priority_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            DummyConstraint(name="bad", priority=-1, relaxable=False)

    def test_repr(self) -> None:
        c = DummyConstraint(name="sector", priority=1, relaxable=True)
        r = repr(c)
        assert "DummyConstraint" in r
        assert "sector" in r
        assert "priority=1" in r
        assert "relaxable=True" in r


# ---------------------------------------------------------------------------
# Tests: get_relaxation_order
# ---------------------------------------------------------------------------


class TestGetRelaxationOrder:
    """Tests for relaxation ordering logic."""

    def _make_constraints(self) -> list[Constraint]:
        """Create a representative set of constraints matching the design."""
        return [
            DummyConstraint(name="box", priority=0, relaxable=False),
            DummyConstraint(name="liquidity", priority=0, relaxable=False),
            DummyConstraint(name="sector_caps", priority=1, relaxable=True),
            DummyConstraint(name="concentration", priority=1, relaxable=True),
            DummyConstraint(name="beta_neutrality", priority=2, relaxable=True),
            DummyConstraint(name="factor_neutrality", priority=2, relaxable=True),
            DummyConstraint(name="tracking_error", priority=2, relaxable=True),
            DummyConstraint(name="turnover", priority=3, relaxable=True),
        ]

    def test_excludes_non_relaxable(self) -> None:
        constraints = self._make_constraints()
        order = get_relaxation_order(constraints)
        names = [c.name for c in order]
        assert "box" not in names
        assert "liquidity" not in names

    def test_sorted_descending_priority(self) -> None:
        constraints = self._make_constraints()
        order = get_relaxation_order(constraints)
        priorities = [c.priority for c in order]
        assert priorities == sorted(priorities, reverse=True)

    def test_highest_priority_first(self) -> None:
        constraints = self._make_constraints()
        order = get_relaxation_order(constraints)
        # Turnover (priority=3) should be first
        assert order[0].name == "turnover"
        assert order[0].priority == 3

    def test_empty_list(self) -> None:
        assert get_relaxation_order([]) == []

    def test_all_non_relaxable(self) -> None:
        constraints = [
            DummyConstraint(name="box", priority=0, relaxable=False),
            DummyConstraint(name="liquidity", priority=0, relaxable=False),
        ]
        assert get_relaxation_order(constraints) == []

    def test_preserves_order_within_same_priority(self) -> None:
        constraints = [
            DummyConstraint(name="beta_neutrality", priority=2, relaxable=True),
            DummyConstraint(name="factor_neutrality", priority=2, relaxable=True),
            DummyConstraint(name="tracking_error", priority=2, relaxable=True),
        ]
        order = get_relaxation_order(constraints)
        names = [c.name for c in order]
        # Stable sort should preserve insertion order within same priority
        assert names == ["beta_neutrality", "factor_neutrality", "tracking_error"]

    def test_count_matches_relaxable_constraints(self) -> None:
        constraints = self._make_constraints()
        order = get_relaxation_order(constraints)
        relaxable_count = sum(1 for c in constraints if c.relaxable)
        assert len(order) == relaxable_count


# ---------------------------------------------------------------------------
# Tests: relax_constraints
# ---------------------------------------------------------------------------


class TestRelaxConstraints:
    """Tests for the relax_constraints generator."""

    def _make_constraints(self) -> list[Constraint]:
        """Create a representative set of constraints."""
        return [
            DummyConstraint(name="box", priority=0, relaxable=False),
            DummyConstraint(name="liquidity", priority=0, relaxable=False),
            DummyConstraint(name="sector_caps", priority=1, relaxable=True),
            DummyConstraint(name="concentration", priority=1, relaxable=True),
            DummyConstraint(name="beta_neutrality", priority=2, relaxable=True),
            DummyConstraint(name="factor_neutrality", priority=2, relaxable=True),
            DummyConstraint(name="tracking_error", priority=2, relaxable=True),
            DummyConstraint(name="turnover", priority=3, relaxable=True),
        ]

    def test_yields_correct_number_of_steps(self) -> None:
        constraints = self._make_constraints()
        steps = list(relax_constraints(constraints))
        relaxable_count = sum(1 for c in constraints if c.relaxable)
        assert len(steps) == relaxable_count

    def test_first_drop_is_highest_priority(self) -> None:
        constraints = self._make_constraints()
        steps = list(relax_constraints(constraints))
        remaining, event = steps[0]
        assert event.constraint_name == "turnover"
        assert event.priority == 3
        assert event.iteration == 1

    def test_iterations_are_one_indexed(self) -> None:
        constraints = self._make_constraints()
        steps = list(relax_constraints(constraints))
        for i, (_, event) in enumerate(steps, start=1):
            assert event.iteration == i

    def test_remaining_shrinks_by_one_each_step(self) -> None:
        constraints = self._make_constraints()
        total = len(constraints)
        for i, (remaining, _) in enumerate(relax_constraints(constraints), start=1):
            assert len(remaining) == total - i

    def test_non_relaxable_always_remain(self) -> None:
        constraints = self._make_constraints()
        for remaining, _ in relax_constraints(constraints):
            names = [c.name for c in remaining]
            assert "box" in names
            assert "liquidity" in names

    def test_events_are_relaxation_event_instances(self) -> None:
        constraints = self._make_constraints()
        for _, event in relax_constraints(constraints):
            assert isinstance(event, RelaxationEvent)

    def test_empty_constraints_yields_nothing(self) -> None:
        steps = list(relax_constraints([]))
        assert steps == []

    def test_only_non_relaxable_yields_nothing(self) -> None:
        constraints = [
            DummyConstraint(name="box", priority=0, relaxable=False),
        ]
        steps = list(relax_constraints(constraints))
        assert steps == []

    def test_final_remaining_has_only_non_relaxable(self) -> None:
        constraints = self._make_constraints()
        steps = list(relax_constraints(constraints))
        final_remaining, _ = steps[-1]
        for c in final_remaining:
            assert c.relaxable is False

    def test_relaxation_order_matches_design(self) -> None:
        """Verify the full relaxation sequence matches the design spec."""
        constraints = self._make_constraints()
        steps = list(relax_constraints(constraints))
        dropped_names = [event.constraint_name for _, event in steps]

        # Turnover (3) first, then priority 2s, then priority 1s
        assert dropped_names[0] == "turnover"
        # Priority 2 constraints next (order within same priority is stable)
        priority_2_dropped = dropped_names[1:4]
        assert set(priority_2_dropped) == {
            "beta_neutrality",
            "factor_neutrality",
            "tracking_error",
        }
        # Priority 1 constraints last
        priority_1_dropped = dropped_names[4:]
        assert set(priority_1_dropped) == {"sector_caps", "concentration"}
