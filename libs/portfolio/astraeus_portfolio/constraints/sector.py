"""Sector constraint: GICS Level 1 sector caps.

Enforces:
    sum(|w_i|) <= sector_max for each GICS L1 sector
    sum(|w_i|) <= unclassified_max for assets without GICS classification

Priority 1, relaxable=True.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cvxpy as cp
import numpy as np

from astraeus_portfolio.constraints.base import Constraint

if TYPE_CHECKING:
    from astraeus_portfolio.contracts import OptContext


class SectorCapConstraint(Constraint):
    """GICS Level 1 sector cap constraint.

    Enforces that the sum of absolute weights in any sector does not exceed
    the configured maximum. Unclassified assets are grouped separately with
    a tighter cap.

    Attributes:
        sector_max: Maximum absolute weight per sector (default 0.25 = 25%).
        unclassified_max: Maximum absolute weight for unclassified bucket (default 0.05 = 5%).
    """

    def __init__(self, sector_max: float = 0.25, unclassified_max: float = 0.05) -> None:
        """Initialize sector cap constraint.

        Args:
            sector_max: Maximum sum of absolute weights per GICS L1 sector.
            unclassified_max: Maximum sum of absolute weights for unclassified assets.

        Raises:
            ValueError: If sector_max or unclassified_max are out of valid range.
        """
        if not (0.0 < sector_max <= 1.0):
            raise ValueError(f"sector_max must be in (0, 1], got {sector_max}")
        if not (0.0 < unclassified_max <= 1.0):
            raise ValueError(f"unclassified_max must be in (0, 1], got {unclassified_max}")

        super().__init__(name="sector_caps", priority=1, relaxable=True)
        self.sector_max = sector_max
        self.unclassified_max = unclassified_max

    def _get_sector_indices(self, ctx: OptContext) -> dict[str, list[int]]:
        """Group asset indices by sector.

        Args:
            ctx: The optimization context with symbols and sector_map.

        Returns:
            Dictionary mapping sector name to list of asset indices.
            Unclassified assets are grouped under "Unclassified".
        """
        sector_indices: dict[str, list[int]] = {}
        for i, symbol in enumerate(ctx.symbols):
            sector = ctx.sector_map.get(symbol, "Unclassified")
            if not sector:
                sector = "Unclassified"
            sector_indices.setdefault(sector, []).append(i)
        return sector_indices

    def to_cvxpy(
        self, w: cp.Variable, ctx: OptContext
    ) -> list[cp.constraints.constraint.Constraint]:
        """Return cvxpy constraints for sector caps.

        For each sector s with indices I_s:
            sum(|w_i| for i in I_s) <= sector_max (or unclassified_max)

        Since we're in long-only mode (box constraint enforces w >= 0),
        |w_i| = w_i, so we use sum(w[indices]) <= cap.

        Args:
            w: The cvxpy weight variable of shape (n_assets,).
            ctx: The optimization context with sector_map.

        Returns:
            List of cvxpy constraints, one per sector.
        """
        constraints: list[cp.constraints.constraint.Constraint] = []
        sector_indices = self._get_sector_indices(ctx)

        for sector, indices in sector_indices.items():
            cap = self.unclassified_max if sector == "Unclassified" else self.sector_max
            # Use cp.sum of absolute values for generality
            constraints.append(cp.sum(cp.abs(w[indices])) <= cap)

        return constraints

    def diagnostic(self, w_value: np.ndarray, ctx: OptContext) -> dict:
        """Report sector cap constraint satisfaction metrics.

        Args:
            w_value: The solved weight vector as a numpy array.
            ctx: The optimization context.

        Returns:
            Dictionary with:
                - satisfied: Whether all sector caps are met.
                - sector_weights: Dict of sector -> total absolute weight.
                - violations: List of sectors exceeding their cap.
        """
        sector_indices = self._get_sector_indices(ctx)
        sector_weights: dict[str, float] = {}
        violations: list[str] = []

        for sector, indices in sector_indices.items():
            total = float(np.sum(np.abs(w_value[indices])))
            sector_weights[sector] = total
            cap = self.unclassified_max if sector == "Unclassified" else self.sector_max
            if total > cap + 1e-8:
                violations.append(sector)

        return {
            "satisfied": len(violations) == 0,
            "sector_weights": sector_weights,
            "violations": violations,
            "sector_max": self.sector_max,
            "unclassified_max": self.unclassified_max,
        }
