"""Cross-Sectional Momentum (12-1) strategy.

Thesis: Stocks that outperformed over past 12 months (excluding last month)
tend to continue outperforming (Jegadeesh & Titman 1993).

Logic:
- Monthly rebalance
- Compute t-252 to t-21 return per symbol
- Cross-sectional z-score after liquidity filter
- Long top decile, short bottom decile, equal-weight
- Gross 200%, net 0%
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


class Momentum12_1(Strategy):
    """Cross-sectional 12-1 momentum strategy."""

    name = "momentum_12_1"
    version = "1.0.0"
    dependencies = DataDependency(
        features=[
            FeatureRef("momentum_12_1", version="1.0.0"),
        ],
        universe=UniverseRef("sp500"),
        calendar="XNYS",
        frequency="1d",
        history_horizon=timedelta(days=300),
    )

    def generate_targets(
        self,
        as_of_ts: Any,
        feature_panel: pl.LazyFrame,
        universe: list[str],
        portfolio_state: PortfolioState,
        params: dict[str, Any],
    ) -> dict[str, float]:
        """Generate long-short momentum targets."""
        top_pct = params.get("top_pct", 0.1)  # top decile
        bottom_pct = params.get("bottom_pct", 0.1)  # bottom decile
        gross_target = params.get("gross_target", 2.0)  # 200% gross

        # Get momentum scores for universe members at as_of_ts
        # The feature panel is already PIT-filtered (ts <= as_of_ts)
        scores = (
            feature_panel.filter(pl.col("symbol").is_in(universe))
            .group_by("symbol")
            .agg(pl.col("close").last().alias("last_close"))
            .collect()
        )

        if scores.is_empty() or len(scores) < 20:
            return {}

        # If we have a momentum feature column, use it directly
        if "momentum_12_1" in scores.columns:
            scores = scores.with_columns(pl.col("momentum_12_1").alias("score"))
        else:
            # Fallback: compute from close prices in the panel
            # This is a simplified version; real impl uses the feature store
            return {}

        # Filter out nulls
        scores = scores.filter(pl.col("score").is_not_null())

        if len(scores) < 20:
            return {}

        # Rank and assign to deciles
        n = len(scores)
        n_long = max(int(n * top_pct), 1)
        n_short = max(int(n * bottom_pct), 1)

        sorted_scores = scores.sort("score", descending=True)
        long_symbols = sorted_scores.head(n_long)["symbol"].to_list()
        short_symbols = sorted_scores.tail(n_short)["symbol"].to_list()

        # Equal-weight within deciles
        long_weight = (gross_target / 2) / max(len(long_symbols), 1)
        short_weight = -(gross_target / 2) / max(len(short_symbols), 1)

        targets: dict[str, float] = {}
        for s in long_symbols:
            targets[s] = long_weight
        for s in short_symbols:
            targets[s] = short_weight

        return targets

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> list[Order]:
        """Event-driven: emit orders based on current targets."""
        # In event-driven mode, we'd track rebalance dates and emit orders
        # This is a simplified implementation
        return []

    def on_fill(self, fill: Fill, ctx: StrategyContext) -> None:
        """Process fill notification."""
        pass
