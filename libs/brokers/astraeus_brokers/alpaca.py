"""Alpaca broker adapter (paper + live).

Uses the alpaca-py SDK. Paper vs live is determined by the ``paper`` flag
in the constructor (which controls the base URL).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide as AlpacaSide
from alpaca.trading.enums import TimeInForce as AlpacaTIF
from alpaca.trading.requests import (
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
)

from astraeus_brokers.base import (
    BrokerAdapter,
    BrokerFill,
    BrokerOrder,
    BrokerOrderStatus,
    BrokerPosition,
    OrderSide,
    OrderType,
    TimeInForce,
)


def _map_side(side: OrderSide) -> AlpacaSide:
    return AlpacaSide.BUY if side == OrderSide.BUY else AlpacaSide.SELL


def _map_tif(tif: TimeInForce) -> AlpacaTIF:
    mapping = {
        TimeInForce.DAY: AlpacaTIF.DAY,
        TimeInForce.GTC: AlpacaTIF.GTC,
    }
    return mapping[tif]


class AlpacaAdapter(BrokerAdapter):
    """Alpaca Trading adapter (paper or live)."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        paper: bool = True,
    ) -> None:
        self._paper = paper
        self._client = TradingClient(
            api_key=api_key,
            secret_key=api_secret,
            paper=paper,
        )

    @property
    def name(self) -> str:
        return "alpaca-paper" if self._paper else "alpaca-live"

    async def submit_order(self, order: BrokerOrder) -> BrokerOrderStatus:
        """Submit order to Alpaca. Idempotent on client_order_id."""
        common: dict[str, Any] = {
            "symbol": order.symbol,
            "qty": float(order.qty),
            "side": _map_side(order.side),
            "time_in_force": _map_tif(order.tif),
            "client_order_id": order.client_order_id,
        }

        if order.order_type == OrderType.MARKET:
            request = MarketOrderRequest(**common)
        else:
            request = LimitOrderRequest(
                **common,
                limit_price=float(order.limit_price) if order.limit_price else None,
            )

        response = self._client.submit_order(request)
        return self._to_status(response)

    async def cancel_order(self, broker_order_id: str) -> BrokerOrderStatus:
        """Cancel an order by broker order ID."""
        self._client.cancel_order_by_id(broker_order_id)
        # Fetch updated status
        return await self.get_order_status(broker_order_id)

    async def get_order_status(self, broker_order_id: str) -> BrokerOrderStatus:
        """Get current order status from Alpaca."""
        response = self._client.get_order_by_id(broker_order_id)
        return self._to_status(response)

    async def get_orders(self, status: str | None = None) -> list[BrokerOrderStatus]:
        """List orders from Alpaca."""
        request = GetOrdersRequest(status=status) if status else GetOrdersRequest()
        orders = self._client.get_orders(request)
        return [self._to_status(o) for o in orders]

    async def get_positions(self) -> list[BrokerPosition]:
        """Get all positions from Alpaca."""
        positions = self._client.get_all_positions()
        return [
            BrokerPosition(
                symbol=p.symbol,
                qty=Decimal(str(p.qty)),
                avg_cost=Decimal(str(p.avg_entry_price)),
                market_value=Decimal(str(p.market_value)) if p.market_value else None,
                unrealized_pnl=(Decimal(str(p.unrealized_pl)) if p.unrealized_pl else None),
            )
            for p in positions
        ]

    async def get_fills(self, since: datetime | None = None) -> list[BrokerFill]:
        """Get fills from Alpaca order history.

        Alpaca doesn't have a dedicated fills endpoint; we reconstruct from
        filled orders.
        """
        request = GetOrdersRequest(status="filled")
        orders = self._client.get_orders(request)
        fills: list[BrokerFill] = []
        for o in orders:
            if since and o.filled_at and o.filled_at < since:
                continue
            if o.filled_qty and o.filled_avg_price:
                fills.append(
                    BrokerFill(
                        broker_fill_id=f"{o.id}-fill",
                        broker_order_id=str(o.id),
                        client_order_id=o.client_order_id or "",
                        symbol=o.symbol,
                        side=OrderSide.BUY if str(o.side) == "buy" else OrderSide.SELL,
                        qty=Decimal(str(o.filled_qty)),
                        price=Decimal(str(o.filled_avg_price)),
                        fees=Decimal("0"),
                        occurred_at=o.filled_at or datetime.now(UTC),
                    )
                )
        return fills

    def _to_status(self, order: Any) -> BrokerOrderStatus:
        """Convert Alpaca order object to BrokerOrderStatus."""
        return BrokerOrderStatus(
            client_order_id=order.client_order_id or "",
            broker_order_id=str(order.id),
            state=str(order.status.value) if order.status else "unknown",
            filled_qty=Decimal(str(order.filled_qty)) if order.filled_qty else Decimal("0"),
            avg_fill_price=(
                Decimal(str(order.filled_avg_price)) if order.filled_avg_price else None
            ),
            rejected_reason=None,
            submitted_at=order.submitted_at,
        )

    async def close(self) -> None:
        """No persistent connection to close for REST client."""
