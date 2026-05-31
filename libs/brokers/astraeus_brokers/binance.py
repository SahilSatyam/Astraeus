"""Binance broker adapter — PAPER TRADING ONLY this phase.

Live trading on Binance is descoped indefinitely. This adapter provides
a paper-trading simulation for crypto pairs, using the same BrokerAdapter
interface as Alpaca and IBKR.

The paper adapter maintains an in-memory order book and simulates fills
at the submitted price (no slippage simulation in this phase).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from astraeus_brokers.base import (
    BrokerAdapter,
    BrokerFill,
    BrokerOrder,
    BrokerOrderStatus,
    BrokerPosition,
    OrderSide,
    OrderType,
)


class BinancePaperAdapter(BrokerAdapter):
    """In-memory paper trading adapter for Binance.

    Simulates order submission and immediate fills for market orders.
    Limit orders are held until explicitly filled (no market data feed).

    This is a scaffold for future live integration.
    """

    def __init__(self) -> None:
        self._orders: dict[str, _PaperOrder] = {}  # broker_order_id -> order
        self._positions: dict[str, _PaperPosition] = {}  # symbol -> position
        self._fills: list[BrokerFill] = []

    @property
    def name(self) -> str:
        return "binance-paper"

    async def submit_order(self, order: BrokerOrder) -> BrokerOrderStatus:
        """Submit a paper order. Market orders fill immediately."""
        # Idempotency: check if client_order_id already exists
        for existing in self._orders.values():
            if existing.client_order_id == order.client_order_id:
                return BrokerOrderStatus(
                    client_order_id=order.client_order_id,
                    broker_order_id=existing.broker_order_id,
                    state=existing.state,
                    filled_qty=existing.filled_qty,
                    avg_fill_price=existing.avg_fill_price,
                    submitted_at=existing.submitted_at,
                )

        broker_order_id = f"binance-paper-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        paper_order = _PaperOrder(
            broker_order_id=broker_order_id,
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            order_type=order.order_type,
            limit_price=order.limit_price,
            submitted_at=now,
        )

        # Market orders fill immediately at a simulated price
        if order.order_type == OrderType.MARKET:
            # Simulate fill at limit_price or a default
            fill_price = order.limit_price or Decimal("100.00")
            paper_order.state = "filled"
            paper_order.filled_qty = order.qty
            paper_order.avg_fill_price = fill_price

            # Record fill
            fill = BrokerFill(
                broker_fill_id=f"{broker_order_id}-fill-1",
                broker_order_id=broker_order_id,
                client_order_id=order.client_order_id,
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                price=fill_price,
                fees=Decimal("0"),
                occurred_at=now,
            )
            self._fills.append(fill)

            # Update position
            self._update_position(order.symbol, order.side, order.qty, fill_price)
        else:
            paper_order.state = "open"

        self._orders[broker_order_id] = paper_order

        return BrokerOrderStatus(
            client_order_id=order.client_order_id,
            broker_order_id=broker_order_id,
            state=paper_order.state,
            filled_qty=paper_order.filled_qty,
            avg_fill_price=paper_order.avg_fill_price,
            submitted_at=now,
        )

    async def cancel_order(self, broker_order_id: str) -> BrokerOrderStatus:
        """Cancel a paper order."""
        order = self._orders.get(broker_order_id)
        if order and order.state == "open":
            order.state = "cancelled"
        return BrokerOrderStatus(
            client_order_id=order.client_order_id if order else "",
            broker_order_id=broker_order_id,
            state=order.state if order else "unknown",
            filled_qty=order.filled_qty if order else Decimal("0"),
        )

    async def get_order_status(self, broker_order_id: str) -> BrokerOrderStatus:
        """Get status of a paper order."""
        order = self._orders.get(broker_order_id)
        if not order:
            return BrokerOrderStatus(
                client_order_id="",
                broker_order_id=broker_order_id,
                state="unknown",
            )
        return BrokerOrderStatus(
            client_order_id=order.client_order_id,
            broker_order_id=broker_order_id,
            state=order.state,
            filled_qty=order.filled_qty,
            avg_fill_price=order.avg_fill_price,
            submitted_at=order.submitted_at,
        )

    async def get_orders(self, status: str | None = None) -> list[BrokerOrderStatus]:
        """List paper orders."""
        results: list[BrokerOrderStatus] = []
        for order in self._orders.values():
            if status and order.state != status:
                continue
            results.append(
                BrokerOrderStatus(
                    client_order_id=order.client_order_id,
                    broker_order_id=order.broker_order_id,
                    state=order.state,
                    filled_qty=order.filled_qty,
                    avg_fill_price=order.avg_fill_price,
                    submitted_at=order.submitted_at,
                )
            )
        return results

    async def get_positions(self) -> list[BrokerPosition]:
        """Get all paper positions."""
        return [
            BrokerPosition(
                symbol=p.symbol,
                qty=p.qty,
                avg_cost=p.avg_cost,
            )
            for p in self._positions.values()
            if p.qty != Decimal("0")
        ]

    async def get_fills(self, since: datetime | None = None) -> list[BrokerFill]:
        """Get paper fills."""
        if since:
            return [f for f in self._fills if f.occurred_at >= since]
        return list(self._fills)

    def _update_position(
        self, symbol: str, side: OrderSide, qty: Decimal, price: Decimal
    ) -> None:
        """Update in-memory position tracking."""
        pos = self._positions.get(symbol)
        if pos is None:
            pos = _PaperPosition(symbol=symbol, qty=Decimal("0"), avg_cost=Decimal("0"))
            self._positions[symbol] = pos

        if side == OrderSide.BUY:
            new_qty = pos.qty + qty
            if new_qty != Decimal("0"):
                pos.avg_cost = ((pos.qty * pos.avg_cost) + (qty * price)) / new_qty
            pos.qty = new_qty
        else:
            pos.qty = pos.qty - qty


class _PaperOrder:
    """Internal paper order state."""

    __slots__ = (
        "broker_order_id",
        "client_order_id",
        "symbol",
        "side",
        "qty",
        "order_type",
        "limit_price",
        "state",
        "filled_qty",
        "avg_fill_price",
        "submitted_at",
    )

    def __init__(
        self,
        broker_order_id: str,
        client_order_id: str,
        symbol: str,
        side: OrderSide,
        qty: Decimal,
        order_type: OrderType,
        limit_price: Decimal | None,
        submitted_at: datetime,
    ) -> None:
        self.broker_order_id = broker_order_id
        self.client_order_id = client_order_id
        self.symbol = symbol
        self.side = side
        self.qty = qty
        self.order_type = order_type
        self.limit_price = limit_price
        self.state = "new"
        self.filled_qty = Decimal("0")
        self.avg_fill_price: Decimal | None = None
        self.submitted_at = submitted_at


class _PaperPosition:
    """Internal paper position state."""

    __slots__ = ("symbol", "qty", "avg_cost")

    def __init__(self, symbol: str, qty: Decimal, avg_cost: Decimal) -> None:
        self.symbol = symbol
        self.qty = qty
        self.avg_cost = avg_cost
