"""Turnover constraint: penalty mode or hard cap.

Supports two modes:
- Penalty mode: adds lambda_turnover * ||w - w_prev||_1 to the objective
  (returns empty constraint list from to_cvxpy, provides penalty_expression).
- Hard cap mode: enforces ||w - w_prev||_1 <= turnover_max as a constraint.

Priority: 3 (relaxed first among all relaxable constraints).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import cvxpy as cp
import numpy as np

from astraeus_portfolio.constraints.base import Constraint

if TYPE_CHECKING:
    from astraeus_portfolio.contracts import OptContext


class TurnoverConstraint(Constraint):
    """Turnover constraint with penalty or hard-cap mode.

    In penalty mode, this is NOT a hard constraint but an objective penalty.
    The optimizer should check for a `penalty_expression` method and add it
    to the objective. `to_cvxpy` returns an empty list in this mode.

    In hard cap mode, `to_cvxpy` returns a constraint enforcing
    ||w - w_prev||_1 <= turnover_max.

    Attributes:
        mode: Either "penalty" or "hard_cap".
        lambda_turnover: Penalty coefficient for L1 turnover (penalty mode).
        turnover_max: Maximum allowed L1 turnover (hard cap mode).
    """

    def __init__(
        self,
        mode: Literal["penalty", "hard_cap"] = "penalty",
        lambda_turnover: float = 0.5,
        turnover_max: float = 0.40,
    ) -> None:
        """Initialize turnover constraint.

        Args:
            mode: "penalty" for objective penalty, "hard_cap" for constraint.
            lambda_turnover: Penalty coefficient (default 0.5).
            turnover_max: Maximum L1 turnover (default 0.40).
        """
        super().__init__(name="turnover", priority=3, relaxable=True)
        self.mode = mode
        self.lambda_turnover = lambda_turnover
        self.turnover_max = turnover_max

    def to_cvxpy(
        self, w: cp.Variable, ctx: OptContext
    ) -> list[cp.constraints.constraint.Constraint]:
        """Convert to cvxpy constraints.

        In penalty mode, returns an empty list (penalty is added to objective
        via `penalty_expression`). In hard cap mode, returns the L1 norm
        constraint.

        Args:
            w: The cvxpy weight variable of shape (n_assets,).
            ctx: The optimization context with current_weights.

        Returns:
            Empty list for penalty mode, or [||w - w_prev||_1 <= turnover_max]
            for hard cap mode.
        """
        if self.mode == "penalty":
            return []

        # Hard cap mode
        w_prev = ctx.current_weights
        return [cp.norm(w - w_prev, 1) <= self.turnover_max]

    def penalty_expression(self, w: cp.Variable, ctx: OptContext) -> cp.Expression:
        """Return the turnover penalty expression for the objective.

        This should be added to the objective by the optimizer when in
        penalty mode.

        Args:
            w: The cvxpy weight variable of shape (n_assets,).
            ctx: The optimization context with current_weights.

        Returns:
            lambda_turnover * ||w - w_prev||_1 as a cvxpy expression.
        """
        w_prev = ctx.current_weights
        return self.lambda_turnover * cp.norm(w - w_prev, 1)

    def diagnostic(self, w_value: np.ndarray, ctx: OptContext) -> dict:
        """Report actual turnover metrics.

        Args:
            w_value: The solved weight vector as a numpy array of shape (n_assets,).
            ctx: The optimization context.

        Returns:
            Dictionary with:
                - satisfied: Whether the constraint is met (always True in
                  penalty mode since it's not a hard constraint).
                - actual_turnover: The L1 norm ||w - w_prev||_1.
                - mode: The constraint mode.
                - turnover_max: The configured maximum (hard cap mode).
                - lambda_turnover: The penalty coefficient (penalty mode).
        """
        actual_turnover = float(np.sum(np.abs(w_value - ctx.current_weights)))

        if self.mode == "penalty":
            satisfied = True  # Penalty mode is always "satisfied"
        else:
            satisfied = actual_turnover <= self.turnover_max + 1e-8

        return {
            "satisfied": satisfied,
            "actual_turnover": actual_turnover,
            "mode": self.mode,
            "turnover_max": self.turnover_max,
            "lambda_turnover": self.lambda_turnover,
        }
