"""Rate shock stress scenario: +200bps parallel rate move.

Applies factor-level shocks representing a +200 basis point parallel shift
in interest rates, with sector-specific impacts derived from rate sensitivity.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from astraeus_portfolio.contracts import ScenarioName, ScenarioResult

from .base import StressContext, StressScenario

# Sector-specific rate sensitivity shocks for a +200bps parallel move.
# Positive values indicate sectors that benefit from rising rates;
# negative values indicate sectors hurt by rising rates.
_RATE_SECTOR_SHOCKS: dict[str, float] = {
    "Financials": 0.04,           # Banks benefit from wider NIM
    "Energy": -0.02,              # Moderate negative (higher discount rates)
    "Materials": -0.03,           # Moderate negative
    "Industrials": -0.04,         # Moderate negative
    "Consumer Discretionary": -0.06,  # Higher borrowing costs hurt spending
    "Information Technology": -0.08,  # Growth stocks hurt by higher discount rates
    "Technology": -0.08,          # Same as IT
    "Communication Services": -0.05,  # Moderate negative
    "Health Care": -0.03,         # Relatively defensive
    "Consumer Staples": -0.02,    # Defensive, low rate sensitivity
    "Utilities": -0.10,           # Bond proxies, highly rate-sensitive
    "Real Estate": -0.12,         # REITs highly rate-sensitive
    "Unclassified": -0.05,        # Market average proxy
}

# Market-wide factor shock for +200bps (equity risk premium compression)
_RATE_MARKET_FACTOR_SHOCK: float = -0.05


class RateShockScenario(StressScenario):
    """Interest rate shock stress scenario.

    Applies factor-level shocks representing a +200bps parallel rate move.
    The market factor shock is applied proportional to historical rate-shock
    beta, plus sector-specific shocks derived from rate sensitivity.

    Financials benefit (positive shock), while rate-sensitive sectors like
    Utilities, Real Estate, and Technology experience larger drawdowns.
    """

    name = ScenarioName.RATE_SHOCK
    description = (
        "Interest rate shock: +200bps parallel rate move with "
        "sector-specific impacts (financials positive, utilities/tech negative)"
    )
    scenario_version = "rate_shock_v1.0"

    def apply(self, weights: np.ndarray, ctx: StressContext) -> ScenarioResult:
        """Apply rate shock to portfolio.

        The shock is computed as:
        - Market factor component: market_beta * market_factor_shock
        - Sector-specific component: sector rate sensitivity shock

        Total asset shock = market_component + sector_component

        Args:
            weights: Portfolio weight vector (n,).
            ctx: Stress context with factor loadings and sector map.

        Returns:
            ScenarioResult with factor and asset contributions.
        """
        n = len(weights)
        asset_shocks = np.zeros(n)
        proxy_assets: list[str] = []

        for i, sym in enumerate(ctx.symbols):
            sector = ctx.sector_map.get(sym, "Unclassified")
            sector_shock = _RATE_SECTOR_SHOCKS.get(sector, _RATE_SECTOR_SHOCKS["Unclassified"])

            # Market factor component (beta-adjusted)
            if ctx.factor_loadings is not None and ctx.factor_loadings.shape[1] > 0:
                market_beta = ctx.factor_loadings[i, 0]
                market_component = market_beta * _RATE_MARKET_FACTOR_SHOCK
            else:
                # No factor loadings — use sector proxy only
                market_component = _RATE_MARKET_FACTOR_SHOCK
                proxy_assets.append(sym)

            # Total shock = market factor + sector-specific rate sensitivity
            asset_shocks[i] = market_component + sector_shock

        return self._decompose_pnl(weights, asset_shocks, ctx, proxy_assets)
