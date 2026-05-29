"""Concentration constraint: top-k weight cap and Herfindahl.

Enforces two concentration limits:
- Top-k: sum of the k largest weights <= top_k_cap (default k=10, cap=0.50).
- Herfindahl: sum of squared weights <= herfindahl_max (default 0.05).

Priority: 1 (relaxed after higher-priority constraints).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cvxpy as cp
import numpy as np

from astraeus_portfolio.constraints.base import Constraint

if TYPE_CHECKING:
    from astraeus_portfolio.contracts import OptContext


class ConcentrationConstraint(Constraint):
    """Concentration constraint enforcing top-k and Herfindahl limits.

    Attributes:
        top_k: Number of largest weights to sum for the top-k cap.
        top_k_cap: Maximum allowed sum of the top-k weights.
        herfindahl_max: Maximum allowed Herfindahl index (sum of squared weights).
    """

    def __init__(
        self,
        top_k: int = 10,
        top_k_cap: float = 0.50,
        herfindahl_max: float = 0.05,
    ) -> None:
        """Initialize concentration constraint.

        Args:
            top_k: Number of largest weights to cap (default 10).
            top_k_cap: Maximum sum of top-k weights (default 0.50).
            herfindahl_max: Maximum Herfindahl index (default 0.05).
        """
        super().__init__(name="concentration", priority=1, relaxable=True)
        self.top_k = top_k
        self.top_k_cap = top_k_cap
        self.herfindahl_max = herfindahl_max

    def to_cvxpy(
        self, w: cp.Variable, ctx: OptContext
    ) -> list[cp.constraints.constraint.Constraint]:
        """Convert to cvxpy constraints.

        Produces two constraints:
        1. Herfindahl: cp.sum_squares(w) <= herfindahl_max
        2. Top-k: cp.sum_largest(w, k) <= top_k_cap

        Args:
            w: The cvxpy weight variable of shape (n_assets,).
            ctx: The optimization context.

        Returns:
            List of cvxpy constraints for concentration limits.
        """
        constraints: list[cp.constraints.constraint.Constraint] = []

        # Herfindahl constraint: sum of squared weights
        constraints.append(cp.sum_squares(w) <= self.herfindahl_max)

        # Top-k constraint: sum of k largest elements
        # Only apply if k < n_assets (otherwise it's just sum(w) which is
        # already handled by the full-investment constraint)
        k = min(self.top_k, ctx.n_assets)
        if k < ctx.n_assets:
            constraints.append(cp.sum_largest(w, k) <= self.top_k_cap)

        return constraints

    def diagnostic(self, w_value: np.ndarray, ctx: OptContext) -> dict:
        """Report concentration metrics for solved weights.

        Args:
            w_value: The solved weight vector as a numpy array of shape (n_assets,).
            ctx: The optimization context.

        Returns:
            Dictionary with:
                - satisfied: Whether both concentration limits are met.
                - herfindahl: Actual Herfindahl index (sum of squared weights).
                - herfindahl_max: Configured maximum.
                - herfindahl_satisfied: Whether Herfindahl limit is met.
                - top_k_sum: Actual sum of top-k weights.
                - top_k_cap: Configured cap.
                - top_k_satisfied: Whether top-k cap is met.
                - top_k: The k value used.
        """
        herfindahl = float(np.sum(w_value**2))
        herfindahl_satisfied = herfindahl <= self.herfindahl_max + 1e-8

        # Sum of k largest weights
        k = min(self.top_k, len(w_value))
        sorted_weights = np.sort(w_value)[::-1]  # Descending
        top_k_sum = float(np.sum(sorted_weights[:k]))
        top_k_satisfied = top_k_sum <= self.top_k_cap + 1e-8

        satisfied = herfindahl_satisfied and top_k_satisfied

        return {
            "satisfied": satisfied,
            "herfindahl": herfindahl,
            "herfindahl_max": self.herfindahl_max,
            "herfindahl_satisfied": herfindahl_satisfied,
            "top_k_sum": top_k_sum,
            "top_k_cap": self.top_k_cap,
            "top_k_satisfied": top_k_satisfied,
            "top_k": k,
        }
