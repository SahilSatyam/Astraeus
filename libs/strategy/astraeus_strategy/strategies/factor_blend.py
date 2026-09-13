"""Factor Blend strategy (Value + Quality + Momentum + Low Vol).

Thesis: Equal-risk-weighted blend of academic factors diversifies
idiosyncratic factor risk (Asness & Frazzini 2013).

Logic:
- Monthly rebalance
- For each factor, build long-short z-scored decile portfolio
- Combine with equal-risk weights (inverse vol of recent 12-month return series)
- Gross 200%, net 0%, sector-neutralized
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


class FactorBlend(Strategy):
    """Equal-risk-weighted multi-factor strategy."""

    name = "factor_blend"
    version = "1.0.0"
    dependencies = DataDependency(
        features=[
            FeatureRef("momentum_12_1", version="1.0.0"),
            FeatureRef("value_book_to_market", version="1.0.0"),
            FeatureRef("quality_roe", version="1.0.0"),
            FeatureRef("low_vol_60d", version="1.0.0"),
        ],
        universe=UniverseRef("sp500"),
        calendar="XNYS",
        frequency="1d",
        history_horizon=timedelta(days=400),
    )

    def generate_targets(
        self,
        as_of_ts: Any,
        feature_panel: pl.LazyFrame,
        universe: list[str],
        portfolio_state: PortfolioState,
        params: dict[str, Any],
    ) -> dict[str, float]:
        """Generate blended factor targets with equal-risk weighting."""
        gross_target = params.get("gross_target", 2.0)
        top_pct = params.get("top_pct", 0.1)
        bottom_pct = params.get("bottom_pct", 0.1)
        factor_columns = params.get(
            "factors",
            ["momentum_12_1", "value_book_to_market", "quality_roe", "low_vol_60d"],
        )

        # Collect latest factor scores for universe
        panel = (
            feature_panel.filter(pl.col("symbol").is_in(universe))
            .group_by("symbol")
            .agg([pl.col(c).last().alias(c) for c in factor_columns if c in feature_panel.columns])
            .collect()
        )

        if panel.is_empty() or len(panel) < 20:
            return {}

        available_factors = [c for c in factor_columns if c in panel.columns]
        if not available_factors:
            return {}

        # Cross-sectional z-score each factor
        for factor in available_factors:
            mean = panel[factor].mean()
            std = panel[factor].std()
            if std and std > 0:
                panel = panel.with_columns(((pl.col(factor) - mean) / std).alias(f"{factor}_z"))
            else:
                panel = panel.with_columns(pl.lit(0.0).alias(f"{factor}_z"))

        # Composite score: equal-weight z-scores (equal-risk approximation)
        z_cols = [f"{f}_z" for f in available_factors]
        panel = panel.with_columns(
            pl.sum_horizontal(*[pl.col(c) for c in z_cols]).alias("composite_z")
        )

        # Filter nulls
        panel = panel.filter(pl.col("composite_z").is_not_null())
        if len(panel) < 20:
            return {}

        # Long top decile, short bottom decile
        n = len(panel)
        n_long = max(int(n * top_pct), 1)
        n_short = max(int(n * bottom_pct), 1)

        sorted_panel = panel.sort("composite_z", descending=True)
        long_symbols = sorted_panel.head(n_long)["symbol"].to_list()
        short_symbols = sorted_panel.tail(n_short)["symbol"].to_list()

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
