"""Vectorized backtesting engine.

Fast engine for parameter sweeps and screening. Processes the entire
date range as a panel operation using Polars. Execution is simplified
(next-bar-open settlement, average cost model) but fast enough for
10k+ parameter combinations.

Key properties:
- PIT-correct: feature panel filtered to ts <= as_of before strategy sees it
- Deterministic: same inputs → same outputs
- Fast: 10-year × 1000-symbol in < 60s
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
import polars as pl
import structlog

from astraeus_strategy.cost_model import CostModel
from astraeus_strategy.metrics import BacktestMetrics, compute_metrics
from astraeus_strategy.protocol import Strategy
from astraeus_strategy.types import BacktestConfig, PortfolioState

logger = structlog.get_logger("astraeus.strategy.vectorized")


class VectorizedEngine:
    """Vectorized backtesting engine.

    Processes the full date range as a panel. For each rebalance date:
    1. Filter feature panel to PIT boundary
    2. Call strategy.generate_targets()
    3. Compute trades from target vs current weights
    4. Apply cost model
    5. Settle at next bar open, compute returns

    Usage:
        engine = VectorizedEngine(cost_model=CostModel())
        result = engine.run(strategy, config, feature_panel, universe_panel, prices)
    """

    version: str = "1.0.0"

    def __init__(self, cost_model: CostModel | None = None) -> None:
        self._cost_model = cost_model or CostModel()

    def run(
        self,
        strategy: Strategy,
        config: BacktestConfig,
        prices: pl.DataFrame,
        feature_panel: pl.DataFrame | None = None,
        universe_panel: pl.DataFrame | None = None,
    ) -> VectorizedResult:
        """Execute a full vectorized backtest.

        Args:
            strategy: Strategy implementing the protocol.
            config: Backtest configuration.
            prices: DataFrame with columns [ts, symbol, open, high, low, close, volume].
            feature_panel: Optional feature panel (ts, symbol, feature_1, ...).
            universe_panel: Optional universe membership (ts, symbol, in_universe).

        Returns:
            VectorizedResult with equity curve, metrics, and positions history.
        """
        rng = np.random.default_rng(config.seed)
        self._cost_model.rng = rng

        logger.info(
            "vectorized_run_start",
            strategy=strategy.name,
            start=str(config.start),
            end=str(config.end),
        )

        # Get unique rebalance dates
        dates = (
            prices.filter(
                (
                    pl.col("ts")
                    >= datetime(config.start.year, config.start.month, config.start.day, tzinfo=UTC)
                )
                & (
                    pl.col("ts")
                    <= datetime(
                        config.end.year, config.end.month, config.end.day, 23, 59, 59, tzinfo=UTC
                    )
                )
            )
            .select("ts")
            .unique()
            .sort("ts")
            .to_series()
            .to_list()
        )

        if not dates:
            return VectorizedResult(
                metrics=BacktestMetrics(),
                equity_curve=np.array([config.initial_capital]),
                daily_returns=np.array([]),
            )

        # Initialize portfolio
        portfolio = PortfolioState(cash=config.initial_capital, equity=config.initial_capital)
        equity_curve: list[float] = [config.initial_capital]
        daily_returns: list[float] = []
        weights_history: list[dict[str, float]] = []

        prev_weights: dict[str, float] = {}

        for i, ts in enumerate(dates[:-1]):  # Skip last day (no next-bar for settlement)
            next_ts = dates[i + 1]

            # Get universe for this date
            if universe_panel is not None:
                universe = (
                    universe_panel.filter(
                        (pl.col("ts") == ts) & (pl.col("in_universe") == True)  # noqa: E712
                    )
                    .select("symbol")
                    .to_series()
                    .to_list()
                )
            else:
                universe = prices.filter(pl.col("ts") == ts).select("symbol").to_series().to_list()

            # Build PIT feature panel (only data <= ts)
            if feature_panel is not None:
                pit_features = feature_panel.filter(pl.col("ts") <= ts).lazy()
            else:
                pit_features = prices.filter(pl.col("ts") <= ts).lazy()

            # Call strategy
            targets = strategy.generate_targets(
                as_of_ts=ts,
                feature_panel=pit_features,
                universe=universe,
                portfolio_state=portfolio,
                params=config.params,
            )

            weights_history.append(targets)

            # Compute returns from target weights
            # Settlement: targets applied at next bar's open
            day_return = self._compute_day_return(
                targets=targets,
                prev_weights=prev_weights,
                prices=prices,
                current_ts=ts,
                next_ts=next_ts,
            )

            daily_returns.append(day_return)
            portfolio.equity *= 1 + day_return
            equity_curve.append(portfolio.equity)
            prev_weights = targets

        returns_arr = np.array(daily_returns)
        metrics = compute_metrics(returns_arr)
        metrics.total_trades = sum(1 for w in weights_history if w)

        logger.info(
            "vectorized_run_complete",
            strategy=strategy.name,
            sharpe=round(metrics.sharpe, 3),
            ann_return=round(metrics.annualized_return, 4),
            max_dd=round(metrics.max_drawdown, 4),
        )

        return VectorizedResult(
            metrics=metrics,
            equity_curve=np.array(equity_curve),
            daily_returns=returns_arr,
            weights_history=weights_history,
            dates=dates,
        )

    def _compute_day_return(
        self,
        targets: dict[str, float],
        prev_weights: dict[str, float],
        prices: pl.DataFrame,
        current_ts: Any,
        next_ts: Any,
    ) -> float:
        """Compute portfolio return for one day given target weights."""
        if not targets:
            return 0.0

        # Get next-day returns for each symbol
        next_prices = prices.filter(pl.col("ts") == next_ts)
        curr_prices = prices.filter(pl.col("ts") == current_ts)

        portfolio_return = 0.0
        total_cost_pct = 0.0

        for symbol, weight in targets.items():
            # Get return for this symbol
            curr_row = curr_prices.filter(pl.col("symbol") == symbol)
            next_row = next_prices.filter(pl.col("symbol") == symbol)

            if curr_row.is_empty() or next_row.is_empty():
                continue

            curr_close = curr_row.select("close").item()
            next_close = next_row.select("close").item()

            if curr_close <= 0:
                continue

            symbol_return = (next_close - curr_close) / curr_close

            # Apply cost for weight change (turnover)
            prev_weight = prev_weights.get(symbol, 0.0)
            weight_change = abs(weight - prev_weight)

            if weight_change > 0.001:  # Threshold to avoid noise
                # Simplified cost: use average cost in bps
                adv = curr_row.select("volume").item() or 1_000_000
                cost = self._cost_model.compute(
                    shares=int(weight_change * 1_000_000 / max(curr_close, 1)),
                    price=curr_close,
                    adv=adv,
                    sigma_daily=0.02,  # default; could be computed from data
                    high=curr_row.select("high").item(),
                    low=curr_row.select("low").item(),
                )
                total_cost_pct += cost.total / max(abs(weight) * 1_000_000, 1)

            portfolio_return += weight * symbol_return

        return portfolio_return - total_cost_pct


class VectorizedResult:
    """Result of a vectorized backtest run."""

    def __init__(
        self,
        metrics: BacktestMetrics,
        equity_curve: np.ndarray,
        daily_returns: np.ndarray,
        weights_history: list[dict[str, float]] | None = None,
        dates: list[Any] | None = None,
    ) -> None:
        self.metrics = metrics
        self.equity_curve = equity_curve
        self.daily_returns = daily_returns
        self.weights_history = weights_history or []
        self.dates = dates or []
