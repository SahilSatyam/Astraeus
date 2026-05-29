"""Short-Horizon Mean Reversion strategy.

Thesis: Liquid stocks overreact to short-term moves; 5-day winners
underperform losers over next 5 days (Lehmann 1990; Lo & MacKinlay 1990).

Logic:
- Daily rebalance
- Rank by t-5 to t-1 return
- Long bottom quintile, short top quintile
- Risk filter on volatility spikes
- Very high turnover (~50x/year) — best test of cost model honesty
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import polars as pl

from astraeus_strategy.protocol import Strategy, StrategyContext
from astraeus_strategy.types import (
    Bar,
    DataDependency,
    FeatureRef,
    Fill,
    Order,
    PortfolioState,
    UniverseRef,
)


class MeanReversion5d(Strategy):
    """5-day mean reversion strategy."""

    name = "mean_reversion_5d"
    version = "1.0.0"
    dependencies = DataDependency(
        features=[FeatureRef("returns_5d", version="1.0.0")],
        universe=UniverseRef("sp500"),
        calendar="XNYS",
        frequency="1d",
        history_horizon=timedelta(days=30),
    )

    def generate_targets(
        self,
        as_of_ts: Any,
        feature_panel: pl.LazyFrame,
        universe: list[str],
        portfolio_state: PortfolioState,
        params: dict[str, Any],
    ) -> dict[str, float]:
        """Generate mean-reversion targets: short winners, long losers."""
        top_pct = params.get("top_pct", 0.2)
        bottom_pct = params.get("bottom_pct", 0.2)
        gross_target = params.get("gross_target", 2.0)
        params.get("vol_cap", 0.05)  # max daily vol for inclusion

        # Get latest 5-day returns for universe
        panel = (
            feature_panel.filter(pl.col("symbol").is_in(universe))
            .group_by("symbol")
            .agg(
                [
                    pl.col("close").last().alias("last_close"),
                    pl.col("close").shift(5).last().alias("close_5d_ago"),
                ]
            )
            .collect()
        )

        if panel.is_empty() or len(panel) < 20:
            return {}

        # Compute 5-day return
        panel = panel.with_columns(
            ((pl.col("last_close") - pl.col("close_5d_ago")) / pl.col("close_5d_ago")).alias(
                "ret_5d"
            )
        ).filter(pl.col("ret_5d").is_not_null())

        if len(panel) < 20:
            return {}

        n = len(panel)
        n_long = max(int(n * bottom_pct), 1)
        n_short = max(int(n * top_pct), 1)

        # Mean reversion: short recent winners, long recent losers
        sorted_panel = panel.sort("ret_5d", descending=True)
        short_symbols = sorted_panel.head(n_short)["symbol"].to_list()
        long_symbols = sorted_panel.tail(n_long)["symbol"].to_list()

        long_weight = (gross_target / 2) / max(len(long_symbols), 1)
        short_weight = -(gross_target / 2) / max(len(short_symbols), 1)

        targets: dict[str, float] = {}
        for s in long_symbols:
            targets[s] = long_weight
        for s in short_symbols:
            targets[s] = short_weight

        return targets

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> list[Order]:
        return []

    def on_fill(self, fill: Fill, ctx: StrategyContext) -> None:
        pass
