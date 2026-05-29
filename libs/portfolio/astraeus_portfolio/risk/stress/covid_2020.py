"""COVID 2020 stress scenario: Feb 19 – Mar 23, 2020.

Applies asset-level shocks calibrated from the COVID-19 market crash.
Reference magnitude: SPY ≈ -33%.
"""

from __future__ import annotations

import numpy as np

from astraeus_portfolio.contracts import ScenarioName, ScenarioResult

from .base import StressContext, StressScenario

# Sector-level shocks calibrated from Feb 19 – Mar 23, 2020 data.
# These represent cumulative returns over the crash period (~24 trading days).
_COVID_SECTOR_SHOCKS: dict[str, float] = {
    "Energy": -0.50,
    "Financials": -0.38,
    "Industrials": -0.37,
    "Real Estate": -0.35,
    "Materials": -0.34,
    "Consumer Discretionary": -0.33,
    "Communication Services": -0.30,
    "Information Technology": -0.28,
    "Technology": -0.28,
    "Health Care": -0.25,
    "Consumer Staples": -0.22,
    "Utilities": -0.27,
    "Unclassified": -0.33,  # Market average proxy
}

# Market-wide average shock (SPY proxy)
_COVID_MARKET_SHOCK: float = -0.33


class COVID2020Scenario(StressScenario):
    """COVID-19 crash stress scenario.

    Applies asset-level shocks from Feb 19, 2020 (peak) to Mar 23, 2020
    (trough). Assets with sufficient historical data use beta-adjusted
    sector shocks; others use sector proxy and are flagged.
    """

    name = ScenarioName.COVID_2020
    description = (
        "COVID-19 crash: asset-level shocks from February 19, 2020 peak "
        "to March 23, 2020 trough (SPY ≈ -33%)"
    )
    scenario_version = "covid_2020_v1.0"

    def apply(self, weights: np.ndarray, ctx: StressContext) -> ScenarioResult:
        """Apply COVID 2020 shocks to portfolio.

        For each asset:
        - Use sector-calibrated shock with beta adjustment if factor
          loadings are available.
        - Otherwise, use sector proxy shock and flag as proxy-estimated.

        Args:
            weights: Portfolio weight vector (n,).
            ctx: Stress context with historical data.

        Returns:
            ScenarioResult with PnL decomposition.
        """
        n = len(weights)
        asset_shocks = np.zeros(n)
        proxy_assets: list[str] = []

        # COVID crash period is ~24 trading days
        min_history_days = 24

        for i, sym in enumerate(ctx.symbols):
            sector = ctx.sector_map.get(sym, "Unclassified")
            sector_shock = _COVID_SECTOR_SHOCKS.get(sector, _COVID_MARKET_SHOCK)

            if ctx.returns_history.shape[0] >= min_history_days:
                # Use sector-calibrated shock with beta adjustment
                if ctx.factor_loadings is not None and ctx.factor_loadings.shape[1] > 0:
                    market_beta = ctx.factor_loadings[i, 0]
                    asset_shocks[i] = sector_shock * abs(market_beta)
                else:
                    asset_shocks[i] = sector_shock
            else:
                # Insufficient data — use sector proxy
                asset_shocks[i] = sector_shock
                proxy_assets.append(sym)

        return self._decompose_pnl(weights, asset_shocks, ctx, proxy_assets)
