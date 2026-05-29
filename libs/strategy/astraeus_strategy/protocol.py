"""Strategy protocol — the interface every strategy must implement.

A strategy is a Python class implementing this protocol. The same strategy
object is consumed by both the vectorized and event-driven engines:

- Vectorized engine calls `generate_targets()` over the full panel at once
- Event-driven engine calls `on_bar()` per (ts, symbol) in temporal order

Three semantic rules enforced at the engine level:
1. PIT enforcement: feature_panel is filtered before being handed to strategy
2. Idempotence: same inputs → same outputs (verified by hash)
3. Deterministic randomness: all RNG goes through ctx.rng
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from astraeus_strategy.types import DataDependency, Fill, Order, PortfolioState

if TYPE_CHECKING:
    import numpy as np
    import polars as pl
    from datetime import datetime


class StrategyContext:
    """Context passed to event-driven strategy callbacks.

    Provides access to portfolio state, market data, and a seeded RNG.
    Strategies must use ctx.rng for any randomness (direct np.random is banned).
    """

    def __init__(
        self,
        portfolio: PortfolioState,
        rng: Any,  # np.random.Generator
        params: dict[str, Any],
        as_of_ts: datetime | None = None,
    ) -> None:
        self.portfolio = portfolio
        self.rng = rng
        self.params = params
        self.as_of_ts = as_of_ts


@runtime_checkable
class Strategy(Protocol):
    """Protocol that all strategies must implement.

    Attributes:
        name: Unique strategy identifier.
        version: Semantic version string (bumped on logic change).
        dependencies: Data requirements declaration.
    """

    name: str
    version: str
    dependencies: DataDependency

    def generate_targets(
        self,
        as_of_ts: datetime,
        feature_panel: pl.LazyFrame,
        universe: list[str],
        portfolio_state: PortfolioState,
        params: dict[str, Any],
    ) -> dict[str, float]:
        """Generate target weights for the portfolio.

        Called by the vectorized engine. Must return {symbol: target_weight}
        where sum(|weights|) <= gross_target (typically 2.0 for 200% gross).

        Args:
            as_of_ts: Current simulation timestamp (PIT boundary).
            feature_panel: Polars LazyFrame with rows where ts <= as_of_ts ONLY.
            universe: List of symbols currently in the universe.
            portfolio_state: Current portfolio state.
            params: Strategy parameters.

        Returns:
            Dict mapping symbol to target weight.
        """
        ...

    def on_bar(self, bar: Any, ctx: StrategyContext) -> list[Order]:
        """Process a new bar in event-driven mode.

        Called once per (ts, symbol) in temporal order. May emit orders.

        Args:
            bar: The new Bar event.
            ctx: Strategy context with portfolio state and RNG.

        Returns:
            List of orders to submit (may be empty).
        """
        ...

    def on_fill(self, fill: Fill, ctx: StrategyContext) -> None:
        """Notification that an order was filled.

        Called by the event-driven engine after a fill occurs.
        Strategy may update internal state.

        Args:
            fill: The fill event.
            ctx: Strategy context.
        """
        ...
