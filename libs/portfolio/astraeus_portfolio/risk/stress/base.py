"""StressScenario ABC for stress testing framework.

All stress scenarios inherit from this base class and implement the `apply`
method to compute portfolio PnL under a specific stress event.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

import numpy as np

from astraeus_portfolio.contracts import ScenarioName, ScenarioResult


@dataclass(frozen=True)
class StressContext:
    """Immutable context for stress scenario computation.

    Attributes:
        symbols: List of asset symbols in portfolio order.
        weights: Portfolio weight vector (n,).
        returns_history: Historical daily returns matrix (T x n).
        factor_loadings: Factor loading matrix (n x k), or None.
        sector_map: Mapping of symbol -> GICS L1 sector.
        adv: Average daily volume in shares (n,).
        prices: Current asset prices (n,).
        nav: Net asset value in USD.
        seed: Deterministic seed for reproducibility.
    """

    symbols: list[str]
    weights: np.ndarray
    returns_history: np.ndarray
    factor_loadings: np.ndarray | None
    sector_map: dict[str, str]
    adv: np.ndarray
    prices: np.ndarray
    nav: Decimal
    seed: int


class StressScenario(ABC):
    """Abstract base class for stress scenarios.

    Each concrete scenario must define:
    - name: The ScenarioName enum value identifying this scenario.
    - description: Human-readable description of the scenario.
    - scenario_version: Version string that changes when calibration data updates.
    - apply(): Compute portfolio PnL under the scenario shocks.
    """

    name: ScenarioName
    description: str
    scenario_version: str

    @abstractmethod
    def apply(self, weights: np.ndarray, ctx: StressContext) -> ScenarioResult:
        """Apply scenario shocks to portfolio weights.

        Args:
            weights: Portfolio weight vector (n,).
            ctx: Stress context with historical data and metadata.

        Returns:
            ScenarioResult with total PnL, factor/asset contributions,
            and proxy-estimated asset flags.

        The sum of all factor_contributions + asset_contributions must equal
        total_pnl_pct within 0.01% NAV tolerance.
        """
        ...

    def _decompose_pnl(
        self,
        weights: np.ndarray,
        asset_shocks: np.ndarray,
        ctx: StressContext,
        proxy_assets: list[str] | None = None,
    ) -> ScenarioResult:
        """Helper to decompose PnL into factor and asset contributions.

        Computes asset-level contributions as w_i * shock_i, then decomposes
        into factor contributions (via factor loadings) and residual asset
        contributions.

        Args:
            weights: Portfolio weight vector (n,).
            asset_shocks: Per-asset shock magnitudes (n,) as decimal returns.
            ctx: Stress context.
            proxy_assets: List of symbols that used proxy estimates.

        Returns:
            ScenarioResult with decomposed PnL.
        """
        if proxy_assets is None:
            proxy_assets = []

        # Asset-level PnL contributions (weight * shock)
        asset_pnl = weights * asset_shocks
        total_pnl = float(asset_pnl.sum())

        # Factor decomposition
        factor_contributions: dict[str, Decimal] = {}
        residual_asset_contributions: dict[str, Decimal] = {}

        if ctx.factor_loadings is not None and ctx.factor_loadings.shape[1] > 0:
            # Estimate factor shocks via least-squares: asset_shocks ≈ B @ f
            # f = (B'B)^-1 B' asset_shocks
            B = ctx.factor_loadings  # (n, k)
            try:
                factor_shocks, _, _, _ = np.linalg.lstsq(B, asset_shocks, rcond=None)
                factor_pnl_per_factor = weights @ B * factor_shocks  # (k,)

                factor_names = [f"factor_{i}" for i in range(B.shape[1])]
                for i, fname in enumerate(factor_names):
                    factor_contributions[fname] = Decimal(str(round(float(factor_pnl_per_factor[i]), 6)))

                # Residual = total asset PnL - sum of factor PnL
                factor_total = float(sum(float(v) for v in factor_contributions.values()))
                residual = asset_pnl - (B @ factor_shocks) * weights

                for i, sym in enumerate(ctx.symbols):
                    residual_asset_contributions[sym] = Decimal(str(round(float(residual[i]), 6)))
            except np.linalg.LinAlgError:
                # If factor decomposition fails, attribute all to assets
                for i, sym in enumerate(ctx.symbols):
                    residual_asset_contributions[sym] = Decimal(str(round(float(asset_pnl[i]), 6)))
        else:
            # No factor loadings — all PnL attributed to assets
            for i, sym in enumerate(ctx.symbols):
                residual_asset_contributions[sym] = Decimal(str(round(float(asset_pnl[i]), 6)))

        # Ensure decomposition sums to total within tolerance
        # Adjust residual to ensure exact sum
        contrib_sum = sum(float(v) for v in factor_contributions.values()) + sum(
            float(v) for v in residual_asset_contributions.values()
        )
        if abs(contrib_sum - total_pnl) > 1e-10 and residual_asset_contributions:
            # Distribute rounding error to first asset
            first_sym = ctx.symbols[0]
            adjustment = total_pnl - contrib_sum
            residual_asset_contributions[first_sym] = Decimal(
                str(round(float(residual_asset_contributions[first_sym]) + adjustment, 6))
            )

        return ScenarioResult(
            scenario_name=self.name,
            scenario_version=self.scenario_version,
            total_pnl_pct=Decimal(str(round(total_pnl * 100, 4))),
            factor_contributions={k: Decimal(str(round(float(v) * 100, 4))) for k, v in factor_contributions.items()},
            asset_contributions={k: Decimal(str(round(float(v) * 100, 4))) for k, v in residual_asset_contributions.items()},
            proxy_estimated_assets=proxy_assets,
        )
