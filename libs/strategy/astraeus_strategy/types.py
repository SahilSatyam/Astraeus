"""Core data types for the strategy research engine.

All types are frozen dataclasses (immutable, hashable) to ensure
deterministic behavior and safe sharing across engine boundaries.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    MOC = "moc"  # Market on close
    MOO = "moo"  # Market on open


class FillStatus(StrEnum):
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class StrategyStatus(StrEnum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    PROMOTED = "promoted"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class Bar:
    """A single OHLCV bar."""

    symbol: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None
    vwap: float | None = None


@dataclass(frozen=True, slots=True)
class Signal:
    """A trading signal emitted by a strategy."""

    symbol: str
    ts: datetime
    raw_score: float
    ranked_score: float = 0.0
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class Target:
    """A target portfolio weight for a symbol."""

    symbol: str
    weight: float  # target weight, |sum(weights)| <= gross_target
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class Order:
    """An order to be submitted to the execution simulator."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str = ""
    side: Side = Side.BUY
    order_type: OrderType = OrderType.MARKET
    quantity: int = 0
    limit_price: float | None = None
    stop_price: float | None = None
    ts: datetime | None = None


@dataclass(frozen=True, slots=True)
class Fill:
    """A fill (execution) of an order."""

    order_id: str
    symbol: str
    side: Side
    quantity: int
    price: float
    commission: float = 0.0
    spread_cost: float = 0.0
    impact_cost: float = 0.0
    slippage: float = 0.0
    ts: datetime | None = None
    status: FillStatus = FillStatus.FILLED


@dataclass(slots=True)
class Position:
    """A position in a single symbol."""

    symbol: str
    quantity: int = 0
    avg_cost: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


@dataclass(slots=True)
class PortfolioState:
    """Current state of the portfolio."""

    cash: float = 1_000_000.0
    positions: dict[str, Position] = field(default_factory=dict)
    equity: float = 1_000_000.0
    timestamp: datetime | None = None

    @property
    def gross_exposure(self) -> float:
        return sum(abs(p.market_value) for p in self.positions.values())

    @property
    def net_exposure(self) -> float:
        return sum(p.market_value for p in self.positions.values())

    @property
    def long_exposure(self) -> float:
        return sum(p.market_value for p in self.positions.values() if p.market_value > 0)

    @property
    def short_exposure(self) -> float:
        return sum(abs(p.market_value) for p in self.positions.values() if p.market_value < 0)


@dataclass(frozen=True, slots=True)
class FeatureRef:
    """Reference to a feature with version pinning."""

    name: str
    version: str = "latest"


@dataclass(frozen=True, slots=True)
class UniverseRef:
    """Reference to a universe with version pinning."""

    name: str
    version: str = "latest"


@dataclass(frozen=True, slots=True)
class DataDependency:
    """Declares what data a strategy needs."""

    features: list[FeatureRef] = field(default_factory=list)
    universe: UniverseRef = field(default_factory=lambda: UniverseRef("sp500"))
    calendar: str = "XNYS"
    frequency: str = "1d"
    history_horizon: timedelta = field(default_factory=lambda: timedelta(days=400))


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Configuration for a backtest run."""

    strategy_name: str
    params: dict[str, Any] = field(default_factory=dict)
    start: date = field(default_factory=lambda: date(2015, 1, 1))
    end: date = field(default_factory=lambda: date(2024, 12, 31))
    initial_capital: float = 1_000_000.0
    seed: int = 42
    engine: str = "vectorized"  # 'vectorized' | 'event_driven'
    cost_model: str = "default"
    universe_id: str = "sp500"
