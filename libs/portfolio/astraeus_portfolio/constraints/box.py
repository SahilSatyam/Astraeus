"""Box constraint: long-only bounds and gross leverage cap.

Enforces:
    - 0 <= w_i <= w_max for each asset (long-only with position cap)
    - ||w||_1 <= L_max (gross leverage limit)

Priority 0, relaxable=False — this constraint is never dropped during
infeasibility resolution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cvxpy as cp
import numpy as np

from astraeus_portfolio.constraints.base import Constraint

if TYPE_CHECKING:
    from astraeus_portfolio.contracts import OptContext


class BoxConstraint(Constraint):
    """Long-only box constraint with gross leverage cap.

    Enforces 0 <= w_i <= w_max for all assets and ||w||_1 <= L_max.

    Attributes:
        w_max: Maximum weight per asset (default 0.10).
        l_max: Maximum gross leverage (default 1.0).
    """

    def __init__(self, w_max: float = 0.10, l_max: float = 1.0) -> None:
        """Initialize box constraint.

        Args:
            w_max: Maximum weight per asset. Must be in (0, 1].
            l_max: Maximum gross leverage (L1 norm of weights). Must be > 0.

        Raises:
            ValueError: If w_max or l_max are out of valid range.
        """
        if not (0.0 < w_max <= 1.0):
            raise ValueError(f"w_max must be in (0, 1], got {w_max}")
        if l_max <= 0.0:
            raise ValueError(f"l_max must be positive, got {l_max}")

        super().__init__(name="box", priority=0, relaxable=False)
        self.w_max = w_max
        self.l_max = l_max

    def to_cvxpy(
        self, w: cp.Variable, ctx: OptContext
    ) -> list[cp.constraints.constraint.Constraint]:
        """Return cvxpy constraints for box bounds and leverage cap.

        Args:
            w: The cvxpy weight variable of shape (n_assets,).
            ctx: The optimization context.

        Returns:
            List of cvxpy constraints: [w >= 0, w <= w_max, ||w||_1 <= l_max].
        """
        return [
            w >= 0,
            w <= self.w_max,
            cp.norm(w, 1) <= self.l_max,
        ]

    def diagnostic(self, w_value: np.ndarray, ctx: OptContext) -> dict:
        """Report box constraint satisfaction metrics.

        Args:
            w_value: The solved weight vector as a numpy array.
            ctx: The optimization context.

        Returns:
            Dictionary with:
                - satisfied: Whether all bounds are met.
                - max_weight: Maximum weight in the portfolio.
                - min_weight: Minimum weight in the portfolio.
                - gross_leverage: L1 norm of the weight vector.
                - w_max: Configured maximum weight.
                - l_max: Configured maximum leverage.
        """
        max_weight = float(np.max(w_value))
        min_weight = float(np.min(w_value))
        gross_leverage = float(np.sum(np.abs(w_value)))

        bounds_satisfied = min_weight >= -1e-8 and max_weight <= self.w_max + 1e-8
        leverage_satisfied = gross_leverage <= self.l_max + 1e-8

        return {
            "satisfied": bounds_satisfied and leverage_satisfied,
            "max_weight": max_weight,
            "min_weight": min_weight,
            "gross_leverage": gross_leverage,
            "w_max": self.w_max,
            "l_max": self.l_max,
        }
