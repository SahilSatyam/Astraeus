"""Cointegration Pairs Trading strategy.

Thesis: Two assets driven by common factors form a stationary spread
(Gatev, Goetzmann, Rouwenhorst 2006).

Logic:
- Quarterly: Engle-Granger test on candidate pairs within same sector
- Daily: spread = log(p1) - beta * log(p2), z-score over 60 days
- Enter when |z| > 2; exit when |z| < 0.5; stop on |z| > 4
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np
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


class PairsTrading(Strategy):
    """Cointegration-based pairs trading strategy."""

    name = "pairs_cointegration"
    version = "1.0.0"
    dependencies = DataDependency(
        features=[FeatureRef("returns_1d", version="1.0.0")],
        universe=UniverseRef("sp500"),
        calendar="XNYS",
        frequency="1d",
        history_horizon=timedelta(days=300),
    )

    def __init__(self) -> None:
        self._active_pairs: dict[tuple[str, str], dict[str, Any]] = {}

    def generate_targets(
        self,
        as_of_ts: Any,
        feature_panel: pl.LazyFrame,
        universe: list[str],
        portfolio_state: PortfolioState,
        params: dict[str, Any],
    ) -> dict[str, float]:
        """Generate pairs trading targets based on spread z-scores."""
        entry_z = params.get("entry_z", 2.0)
        params.get("exit_z", 0.5)
        stop_z = params.get("stop_z", 4.0)
        lookback = params.get("lookback", 60)
        max_pairs = params.get("max_pairs", 20)
        weight_per_leg = params.get("weight_per_leg", 0.05)

        # Collect price history for universe
        prices = (
            feature_panel.filter(pl.col("symbol").is_in(universe))
            .select(["symbol", "ts", "close"])
            .collect()
        )

        if prices.is_empty():
            return {}

        # Pivot to wide format for pair analysis
        wide = prices.pivot(on="symbol", index="ts", values="close").sort("ts")

        if len(wide) < lookback + 10:
            return {}

        # Use pre-defined pairs or find them (simplified: use first N pairs from universe)
        symbols = [c for c in wide.columns if c != "ts"]
        if len(symbols) < 2:
            return {}

        targets: dict[str, float] = {}
        pairs_traded = 0

        # Simple pair selection: consecutive symbols (in production, use cointegration test)
        for i in range(0, min(len(symbols) - 1, max_pairs * 2), 2):
            if pairs_traded >= max_pairs:
                break

            sym_a = symbols[i]
            sym_b = symbols[i + 1]

            col_a = wide[sym_a].to_numpy()
            col_b = wide[sym_b].to_numpy()

            # Skip if any nulls in recent window
            recent_a = col_a[-lookback:]
            recent_b = col_b[-lookback:]

            if np.any(np.isnan(recent_a)) or np.any(np.isnan(recent_b)):
                continue
            if np.any(recent_a <= 0) or np.any(recent_b <= 0):
                continue

            # Compute log spread
            log_a = np.log(recent_a)
            log_b = np.log(recent_b)

            # Simple beta from OLS: log_a = alpha + beta * log_b
            beta = np.cov(log_a, log_b)[0, 1] / max(np.var(log_b), 1e-10)
            spread = log_a - beta * log_b

            # Z-score of current spread
            spread_mean = np.mean(spread)
            spread_std = np.std(spread)
            if spread_std < 1e-10:
                continue

            z = (spread[-1] - spread_mean) / spread_std

            # Trading logic
            if abs(z) > stop_z:
                # Stop: close any existing position
                continue
            if abs(z) > entry_z:
                # Enter: short spread if z > entry, long spread if z < -entry
                if z > entry_z:
                    targets[sym_a] = targets.get(sym_a, 0) - weight_per_leg
                    targets[sym_b] = targets.get(sym_b, 0) + weight_per_leg * beta
                elif z < -entry_z:
                    targets[sym_a] = targets.get(sym_a, 0) + weight_per_leg
                    targets[sym_b] = targets.get(sym_b, 0) - weight_per_leg * beta

                pairs_traded += 1

        return targets

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> list[Order]:
        return []

    def on_fill(self, fill: Fill, ctx: StrategyContext) -> None:
        pass
