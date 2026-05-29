"""Liquidity constraint: ADV-based position sizing.

Enforces:
    |w_i - w_prev_i| * NAV <= adv_pct * ADV_i * price_i

This limits the dollar trade size for each asset to a fraction of its
average daily volume, preventing market impact from large trades.

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


class LiquidityConstraint(Constraint):
    """ADV-based liquidity constraint.

    Enforces |w_i - w_prev_i| * NAV <= adv_pct * ADV_i * price_i for each asset.

    Attributes:
        adv_pct: Fraction of ADV allowed per trade (default 0.05 = 5%).
    """

    def __init__(self, adv_pct: float = 0.05) -> None:
        """Initialize liquidity constraint.

        Args:
            adv_pct: Maximum fraction of ADV that can be traded. Must be in (0, 1].

        Raises:
            ValueError: If adv_pct is out of valid range.
        """
        if not (0.0 < adv_pct <= 1.0):
            raise ValueError(f"adv_pct must be in (0, 1], got {adv_pct}")

        super().__init__(name="liquidity", priority=0, relaxable=False)
        self.adv_pct = adv_pct

    def to_cvxpy(
        self, w: cp.Variable, ctx: OptContext
    ) -> list[cp.constraints.constraint.Constraint]:
        """Return cvxpy constraints for ADV-based sizing.

        For each asset i:
            |w_i - w_prev_i| * NAV <= adv_pct * ADV_i * price_i

        This is linearized as:
            w_i - w_prev_i <= limit_i / NAV
            w_prev_i - w_i <= limit_i / NAV

        Args:
            w: The cvxpy weight variable of shape (n_assets,).
            ctx: The optimization context containing adv, prices, current_weights, nav.

        Returns:
            List of cvxpy constraints enforcing the ADV limit.
        """
        nav = float(ctx.nav)
        # limit_i = adv_pct * ADV_i * price_i (dollar volume limit per asset)
        limits = self.adv_pct * ctx.adv * ctx.prices
        # Convert to weight-space: max weight change = limit / NAV
        max_weight_change = limits / nav

        w_prev = ctx.current_weights

        return [
            w - w_prev <= max_weight_change,
            w_prev - w <= max_weight_change,
        ]

    def diagnostic(self, w_value: np.ndarray, ctx: OptContext) -> dict:
        """Report liquidity constraint satisfaction metrics.

        Args:
            w_value: The solved weight vector as a numpy array.
            ctx: The optimization context.

        Returns:
            Dictionary with:
                - satisfied: Whether all ADV limits are met.
                - max_adv_usage_pct: Maximum ADV usage across all assets.
                - n_violations: Number of assets exceeding the limit.
                - adv_pct: Configured ADV fraction.
        """
        nav = float(ctx.nav)
        limits = self.adv_pct * ctx.adv * ctx.prices
        max_weight_change = limits / nav

        actual_changes = np.abs(w_value - ctx.current_weights)

        # Compute ADV usage as fraction of limit
        with np.errstate(divide="ignore", invalid="ignore"):
            adv_usage = np.where(max_weight_change > 0, actual_changes / max_weight_change, 0.0)

        n_violations = int(np.sum(actual_changes > max_weight_change + 1e-8))
        max_usage = float(np.max(adv_usage)) if len(adv_usage) > 0 else 0.0

        return {
            "satisfied": n_violations == 0,
            "max_adv_usage_pct": max_usage,
            "n_violations": n_violations,
            "adv_pct": self.adv_pct,
        }
