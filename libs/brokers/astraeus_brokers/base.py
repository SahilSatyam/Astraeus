"""Broker adapter abstract base class.

Every broker (Alpaca, IBKR, Binance) implements this interface. The OMS/EMS
boundary is this ABC — the OMS never touches broker-specific code directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(StrEnum):
    DAY = "DAY"
    GTC = "GTC"


class BrokerOrder(BaseModel):
    """Broker-neutral order request sent from OMS to EMS."""

    client_order_id: str
    symbol: str
    side: OrderSide
    qty: Decimal
    order_type: OrderType
    limit_price: Decimal | None = None
    tif: TimeInForce = TimeInForce.DAY

    model_config = {"frozen": True}


class BrokerOrderStatus(BaseModel):
    """Status returned by the broker after submission or query."""

    client_order_id: str
    broker_order_id: str | None = None
    state: str  # broker-native state string
    filled_qty: Decimal = Decimal("0")
    avg_fill_price: Decimal | None = None
    rejected_reason: str | None = None
    submitted_at: datetime | None = None


class BrokerFill(BaseModel):
    """A single fill event from the broker."""

    broker_fill_id: str
    broker_order_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    qty: Decimal
    price: Decimal
    fees: Decimal = Decimal("0")
    occurred_at: datetime


class BrokerPosition(BaseModel):
    """Current position as reported by the broker."""

    symbol: str
    qty: Decimal
    avg_cost: Decimal
    market_value: Decimal | None = None
    unrealized_pnl: Decimal | None = None


class BrokerAdapter(ABC):
    """Abstract broker adapter. One implementation per broker.

    All methods are async to support non-blocking IO with broker APIs.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Broker identifier (e.g. 'alpaca-paper', 'ibkr')."""
        ...

    @abstractmethod
    async def submit_order(self, order: BrokerOrder) -> BrokerOrderStatus:
        """Submit an order to the broker. Must be idempotent on client_order_id."""
        ...

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> BrokerOrderStatus:
        """Request cancellation of an order."""
        ...

    @abstractmethod
    async def get_order_status(self, broker_order_id: str) -> BrokerOrderStatus:
        """Query current status of an order."""
        ...

    @abstractmethod
    async def get_orders(self, status: str | None = None) -> list[BrokerOrderStatus]:
        """List orders, optionally filtered by status."""
        ...

    @abstractmethod
    async def get_positions(self) -> list[BrokerPosition]:
        """Get all current positions from the broker."""
        ...

    @abstractmethod
    async def get_fills(self, since: datetime | None = None) -> list[BrokerFill]:
        """Get fills since a given time."""
        ...

    async def close(self) -> None:
        """Clean up resources (connections, sessions). Override if needed."""
