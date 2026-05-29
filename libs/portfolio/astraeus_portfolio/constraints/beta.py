"""Beta neutrality constraint.

Enforces:
    |beta' * w - beta_target| <= tolerance

This keeps the portfolio's market beta close to a target value (default 0),
ensuring approximate market neutrality.

Priority 2, relaxable=True.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cvxpy as cp
import numpy as np

from astraeus_portfolio.constraints.base import Constraint

if TYPE_CHECKING:
    from astraeus_portfolio.contracts import OptContext


class BetaNeutralityConstraint(Constraint):
    """Beta neutrality constraint.

    Enforces |beta' * w - beta_target| <= tolerance.

    Attributes:
        beta_target: Target portfolio beta (default 0.0 for market neutral).
        tolerance: Maximum deviation from target (default 0.05).
    """

    def __init__(self, beta_target: float = 0.0, tolerance: float = 0.05) -> None:
        """Initialize beta neutrality constraint.

        Args:
            beta_target: Target portfolio beta.
            tolerance: Maximum allowed deviation from target.

        Raises:
            ValueError: If tolerance is non-positive.
        """
        if tolerance <= 0.0:
            raise ValueError(f"tolerance must be positive, got {tolerance}")

        super().__init__(name="beta_neutrality", priority=2, relaxable=True)
        self.beta_target = beta_target
        self.tolerance = tolerance

    def to_cvxpy(
        self, w: cp.Variable, ctx: OptContext
    ) -> list[cp.constraints.constraint.Constraint]:
        """Return cvxpy constraints for beta neutrality.

        Enforces: |beta' * w - beta_target| <= tolerance
        Linearized as:
            beta' * w - beta_target <= tolerance
            beta_target - beta' * w <= tolerance

        Args:
            w: The cvxpy weight variable of shape (n_assets,).
            ctx: The optimization context containing beta vector.

        Returns:
            List of cvxpy constraints enforcing beta neutrality.
        """
        portfolio_beta = ctx.beta @ w
        return [
            portfolio_beta - self.beta_target <= self.tolerance,
            self.beta_target - portfolio_beta <= self.tolerance,
        ]

    def diagnostic(self, w_value: np.ndarray, ctx: OptContext) -> dict:
        """Report beta neutrality constraint satisfaction metrics.

        Args:
            w_value: The solved weight vector as a numpy array.
            ctx: The optimization context.

        Returns:
            Dictionary with:
                - satisfied: Whether beta is within tolerance of target.
                - portfolio_beta: Realized portfolio beta.
                - beta_target: Target beta.
                - tolerance: Configured tolerance.
                - deviation: Absolute deviation from target.
        """
        portfolio_beta = float(ctx.beta @ w_value)
        deviation = abs(portfolio_beta - self.beta_target)

        return {
            "satisfied": deviation <= self.tolerance + 1e-8,
            "portfolio_beta": portfolio_beta,
            "beta_target": self.beta_target,
            "tolerance": self.tolerance,
            "deviation": deviation,
        }
