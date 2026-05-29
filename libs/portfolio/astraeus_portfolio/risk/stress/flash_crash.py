"""Flash crash stress scenario: May 6, 2010 intraday (14:42–14:47 ET).

Applies intraday asset-level shocks from the May 6, 2010 Flash Crash event
with liquidity set to zero (adv_pct=0) during the shock window.
"""

from __future__ import annotations

import numpy as np

from astraeus_portfolio.contracts import ScenarioName, ScenarioResult

from .base import StressContext, StressScenario

# Sector-level intraday shocks calibrated from May 6, 2010 14:42–14:47 ET.
# These represent the maximum drawdown during the 5-minute crash window.
_FLASH_CRASH_SECTOR_SHOCKS: dict[str, float] = {
    "Consumer Discretionary": -0.12,
    "Consumer Staples": -0.06,
    "Energy": -0.08,
    "Financials": -0.10,
    "Health Care": -0.07,
    "Industrials": -0.10,
    "Information Technology": -0.09,
    "Technology": -0.09,
    "Materials": -0.09,
    "Communication Services": -0.08,
    "Utilities": -0.06,
    "Real Estate": -0.08,
    "Unclassified": -0.09,  # Market average proxy
}

# Market-wide average intraday shock
_FLASH_CRASH_MARKET_SHOCK: float = -0.09

# During flash crash, liquidity is zero — no ability to trade
_FLASH_CRASH_ADV_PCT: float = 0.0


class FlashCrashScenario(StressScenario):
    """May 6, 2010 Flash Crash stress scenario.

    Applies intraday asset-level shocks from the 14:42–14:47 ET maximum
    drawdown window. Liquidity is set to zero (adv_pct=0) during the shock,
    meaning no position can be liquidated during the event.

    This scenario tests portfolio resilience to sudden, extreme intraday
    moves with complete liquidity evaporation.
    """

    name = ScenarioName.FLASH_CRASH
    description = (
        "Flash Crash: intraday shocks from May 6, 2010 (14:42–14:47 ET) "
        "with zero liquidity (adv_pct=0)"
    )
    scenario_version = "flash_crash_v1.0"

    # Liquidity parameter: zero during flash crash
    adv_pct: float = _FLASH_CRASH_ADV_PCT

    def apply(self, weights: np.ndarray, ctx: StressContext) -> ScenarioResult:
        """Apply flash crash shocks to portfolio.

        All positions are fully exposed to the shock since adv_pct=0
        means no liquidity is available to reduce positions during the event.

        For each asset:
        - Apply sector-calibrated intraday shock.
        - If factor loadings available, scale by market beta for
          more volatile assets.
        - Assets without data use sector proxy.

        Args:
            weights: Portfolio weight vector (n,).
            ctx: Stress context with historical data.

        Returns:
            ScenarioResult with PnL decomposition.
        """
        n = len(weights)
        asset_shocks = np.zeros(n)
        proxy_assets: list[str] = []

        for i, sym in enumerate(ctx.symbols):
            sector = ctx.sector_map.get(sym, "Unclassified")
            sector_shock = _FLASH_CRASH_SECTOR_SHOCKS.get(sector, _FLASH_CRASH_MARKET_SHOCK)

            if ctx.returns_history.shape[0] >= 10:
                # Use sector shock with beta scaling for more volatile assets
                if ctx.factor_loadings is not None and ctx.factor_loadings.shape[1] > 0:
                    market_beta = ctx.factor_loadings[i, 0]
                    # Flash crash amplifies high-beta assets
                    asset_shocks[i] = sector_shock * max(abs(market_beta), 1.0)
                else:
                    asset_shocks[i] = sector_shock
            else:
                # Insufficient data — use sector proxy
                asset_shocks[i] = sector_shock
                proxy_assets.append(sym)

        return self._decompose_pnl(weights, asset_shocks, ctx, proxy_assets)
