"""Factor neutrality constraint.

Enforces that the portfolio has zero exposure to each factor in the factor
loading matrix: B_factors' * w = 0 for each factor column.

Relaxation: priority=2, relaxable=True.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cvxpy as cp
import numpy as np

from astraeus_portfolio.constraints.base import Constraint

if TYPE_CHECKING:
    from astraeus_portfolio.contracts import OptContext


class FactorNeutralityConstraint(Constraint):
    """Enforce zero factor exposure across all factors.

    Given a factor loading matrix of shape (n_assets, k_factors), this
    constraint enforces that the portfolio weight vector has zero exposure
    to each factor: factor_loadings.T @ w == 0.

    This is a hard equality constraint per factor column.
    """

    def __init__(self) -> None:
        """Initialize factor neutrality constraint."""
        super().__init__(name="factor_neutrality", priority=2, relaxable=True)

    def to_cvxpy(
        self, w: cp.Variable, ctx: OptContext
    ) -> list[cp.constraints.constraint.Constraint]:
        """Build cvxpy constraints for factor neutrality.

        Creates one equality constraint per factor column in the loading matrix.
        If ``ctx.factor_loadings`` is None, returns an empty list (no constraint).

        Args:
            w: The cvxpy weight variable of shape (n_assets,).
            ctx: Optimization context with ``factor_loadings`` of shape
                (n_assets, k_factors) or None.

        Returns:
            A list of cvxpy equality constraints, one per factor. Empty list
            if factor_loadings is not available.
        """
        if ctx.factor_loadings is None:
            return []

        # factor_loadings shape: (n_assets, k_factors)
        # For each factor column j: factor_loadings[:, j].T @ w == 0
        constraints: list[cp.constraints.constraint.Constraint] = []
        n_factors = ctx.factor_loadings.shape[1]
        for j in range(n_factors):
            factor_col = ctx.factor_loadings[:, j]
            constraints.append(factor_col @ w == 0)

        return constraints

    def diagnostic(self, w_value: np.ndarray, ctx: OptContext) -> dict:
        """Report factor exposures for the solved portfolio.

        Args:
            w_value: Solved weight vector of shape (n_assets,).
            ctx: Optimization context with ``factor_loadings``.

        Returns:
            Dictionary with:
                - 'satisfied': Whether all factor exposures are approximately zero.
                - 'factor_exposures': List of per-factor exposure values.
                - 'max_absolute_exposure': The largest absolute factor exposure.
                - 'n_factors': Number of factors in the loading matrix.
        """
        if ctx.factor_loadings is None:
            return {
                "satisfied": True,
                "factor_exposures": [],
                "max_absolute_exposure": 0.0,
                "n_factors": 0,
            }

        # Compute factor exposures: factor_loadings.T @ w
        exposures = ctx.factor_loadings.T @ w_value
        factor_exposures = [float(e) for e in exposures]
        max_abs_exposure = float(np.max(np.abs(exposures))) if len(exposures) > 0 else 0.0

        # Tolerance for numerical precision
        satisfied = max_abs_exposure <= 1e-6

        return {
            "satisfied": satisfied,
            "factor_exposures": factor_exposures,
            "max_absolute_exposure": max_abs_exposure,
            "n_factors": ctx.factor_loadings.shape[1],
        }
