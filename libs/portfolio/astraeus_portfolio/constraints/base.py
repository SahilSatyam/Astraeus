"""Constraint ABC with priority-based relaxation ordering.

This module defines the abstract base class for all portfolio constraints and
provides helper functions for relaxation ordering during infeasibility resolution.

Relaxation order (ascending priority — higher priority is relaxed first):
    turnover (3) → factor neutrality (2) → beta neutrality (2) →
    tracking error (2) → sector caps (1) → concentration (1) →
    liquidity (0, never) → box (0, never)

Priority 0 constraints (box, liquidity) are NEVER relaxed (relaxable=False).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Generator
from typing import TYPE_CHECKING

import cvxpy as cp
import numpy as np

from astraeus_portfolio.contracts import RelaxationEvent

if TYPE_CHECKING:
    from astraeus_portfolio.contracts import OptContext


class Constraint(ABC):
    """Abstract base class for portfolio constraints.

    Each constraint translates a portfolio restriction into one or more cvxpy
    constraint expressions and carries metadata for priority-based relaxation.

    Attributes:
        name: Human-readable constraint identifier.
        priority: Relaxation priority (0 = never relaxed, higher = relaxed first).
        relaxable: Whether this constraint can be dropped during infeasibility
            resolution. Must be False when priority is 0.
    """

    name: str
    priority: int
    relaxable: bool

    def __init__(self, name: str, priority: int, relaxable: bool) -> None:
        """Initialize constraint with name, priority, and relaxable flag.

        Args:
            name: Human-readable constraint identifier.
            priority: Relaxation priority (0 = never relaxed, higher = relaxed first).
            relaxable: Whether this constraint can be dropped during relaxation.

        Raises:
            ValueError: If priority is 0 but relaxable is True, or if priority < 0.
        """
        if priority < 0:
            raise ValueError(f"Priority must be non-negative, got {priority}")
        if priority == 0 and relaxable:
            raise ValueError(
                f"Constraint '{name}' has priority 0 but relaxable=True. "
                "Priority 0 constraints must never be relaxed."
            )
        self.name = name
        self.priority = priority
        self.relaxable = relaxable

    @abstractmethod
    def to_cvxpy(self, w: cp.Variable, ctx: OptContext) -> list[cp.constraints.constraint.Constraint]:
        """Convert this constraint to cvxpy constraint expressions.

        Args:
            w: The cvxpy weight variable of shape (n_assets,).
            ctx: The optimization context containing auxiliary data
                (covariance, betas, sector map, etc.).

        Returns:
            A list of cvxpy constraint objects to be added to the problem.
        """
        ...

    @abstractmethod
    def diagnostic(self, w_value: np.ndarray, ctx: OptContext) -> dict:
        """Return constraint-satisfaction metrics for solved weights.

        This method is called after optimization to report whether the
        constraint is satisfied and by how much.

        Args:
            w_value: The solved weight vector as a numpy array of shape (n_assets,).
            ctx: The optimization context.

        Returns:
            A dictionary containing at minimum:
                - 'satisfied': bool indicating if the constraint is met
                - Additional constraint-specific metrics (slack, violation magnitude, etc.)
        """
        ...

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(name={self.name!r}, "
            f"priority={self.priority}, relaxable={self.relaxable})"
        )


def get_relaxation_order(constraints: list[Constraint]) -> list[Constraint]:
    """Return relaxable constraints sorted by descending priority for relaxation.

    Constraints with higher priority values are relaxed first. Within the same
    priority level, the original insertion order is preserved (stable sort).

    Priority 0 constraints and those with relaxable=False are excluded.

    Args:
        constraints: Full list of constraints (both relaxable and non-relaxable).

    Returns:
        A list of relaxable constraints sorted by descending priority
        (highest priority first, meaning they get dropped first).
    """
    relaxable = [c for c in constraints if c.relaxable and c.priority > 0]
    # Sort by descending priority — higher priority constraints are relaxed first
    relaxable.sort(key=lambda c: c.priority, reverse=True)
    return relaxable


def relax_constraints(
    constraints: list[Constraint],
) -> Generator[tuple[list[Constraint], RelaxationEvent], None, None]:
    """Yield (remaining_constraints, event) tuples as constraints are dropped.

    Drops relaxable constraints one at a time in descending priority order
    (highest priority first). Emits a RelaxationEvent for each constraint
    dropped, with a 1-indexed iteration count.

    Priority 0 constraints are never dropped.

    Args:
        constraints: The full list of constraints for the optimization problem.

    Yields:
        Tuples of (remaining_constraints, relaxation_event) where:
            - remaining_constraints: The constraint list with one more constraint removed.
            - relaxation_event: A RelaxationEvent recording what was dropped.

    Example:
        >>> for remaining, event in relax_constraints(all_constraints):
        ...     result = solve(remaining)
        ...     if result.status == "optimal":
        ...         break
    """
    relaxation_order = get_relaxation_order(constraints)

    # Start with all constraints; progressively remove relaxable ones
    remaining = list(constraints)

    for iteration, constraint_to_drop in enumerate(relaxation_order, start=1):
        remaining = [c for c in remaining if c is not constraint_to_drop]

        event = RelaxationEvent(
            constraint_name=constraint_to_drop.name,
            priority=constraint_to_drop.priority,
            iteration=iteration,
        )

        yield remaining, event
