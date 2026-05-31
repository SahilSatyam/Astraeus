"""Interactive Brokers adapter via ib_insync.

This adapter connects to TWS or IB Gateway. It implements the same
BrokerAdapter interface as Alpaca, allowing the OMS to be broker-agnostic.

Note: ib_insync is an optional dependency. Import errors are caught at
instantiation time with a clear error message.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

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


class IBKRAdapter(BrokerAdapter):
    """Interactive Brokers adapter using ib_insync.

    Requires TWS or IB Gateway running on the specified host/port.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,  # 7497 = paper, 7496 = live
        client_id: int = 1,
        paper: bool = True,
    ) -> None:
        try:
            from ib_insync import IB
        except ImportError as e:
            msg = "ib_insync is required for IBKR adapter. Install with: pip install ib_insync"
            raise ImportError(msg) from e

        self._paper = paper
        self._host = host
        self._port = port
        self._client_id = client_id
        self._ib: Any = IB()
        self._connected = False

    @property
    def name(self) -> str:
        return "ibkr-paper" if self._paper else "ibkr-live"

    async def _ensure_connected(self) -> None:
        """Connect to TWS/Gateway if not already connected."""
        if not self._connected:
            self._ib.connect(self._host, self._port, clientId=self._client_id)
            self._connected = True

    async def submit_order(self, order: BrokerOrder) -> BrokerOrderStatus:
        """Submit order to IBKR."""
        from ib_insync import LimitOrder, MarketOrder, Stock

        await self._ensure_connected()

        contract = Stock(order.symbol, "SMART", "USD")
        action = "BUY" if order.side == OrderSide.BUY else "SELL"

        if order.order_type == OrderType.MARKET:
            ib_order = MarketOrder(action, float(order.qty))
        else:
            ib_order = LimitOrder(action, float(order.qty), float(order.limit_price or 0))

        # Set client order ID for idempotency
        ib_order.orderRef = order.client_order_id

        tif_map = {TimeInForce.DAY: "DAY", TimeInForce.GTC: "GTC"}
        ib_order.tif = tif_map.get(order.tif, "DAY")

        trade = self._ib.placeOrder(contract, ib_order)
        return BrokerOrderStatus(
            client_order_id=order.client_order_id,
            broker_order_id=str(trade.order.orderId),
            state=trade.orderStatus.status if trade.orderStatus else "Submitted",
            filled_qty=Decimal(str(trade.orderStatus.filled))
            if trade.orderStatus
            else Decimal("0"),
            avg_fill_price=(
                Decimal(str(trade.orderStatus.avgFillPrice))
                if trade.orderStatus and trade.orderStatus.avgFillPrice
                else None
            ),
            submitted_at=datetime.now(UTC),
        )

    async def cancel_order(self, broker_order_id: str) -> BrokerOrderStatus:
        """Cancel an order by broker order ID."""
        await self._ensure_connected()
        # Find the trade by order ID
        for trade in self._ib.trades():
            if str(trade.order.orderId) == broker_order_id:
                self._ib.cancelOrder(trade.order)
                return BrokerOrderStatus(
                    client_order_id=trade.order.orderRef or "",
                    broker_order_id=broker_order_id,
                    state="PendingCancel",
                    filled_qty=Decimal(str(trade.orderStatus.filled)),
                )
        return BrokerOrderStatus(
            client_order_id="",
            broker_order_id=broker_order_id,
            state="unknown",
        )

    async def get_order_status(self, broker_order_id: str) -> BrokerOrderStatus:
        """Get order status from IBKR."""
        await self._ensure_connected()
        for trade in self._ib.trades():
            if str(trade.order.orderId) == broker_order_id:
                return BrokerOrderStatus(
                    client_order_id=trade.order.orderRef or "",
                    broker_order_id=broker_order_id,
                    state=trade.orderStatus.status,
                    filled_qty=Decimal(str(trade.orderStatus.filled)),
                    avg_fill_price=(
                        Decimal(str(trade.orderStatus.avgFillPrice))
                        if trade.orderStatus.avgFillPrice
                        else None
                    ),
                )
        return BrokerOrderStatus(
            client_order_id="",
            broker_order_id=broker_order_id,
            state="unknown",
        )

    async def get_orders(self, status: str | None = None) -> list[BrokerOrderStatus]:
        """List all open orders from IBKR."""
        await self._ensure_connected()
        results: list[BrokerOrderStatus] = []
        for trade in self._ib.trades():
            s = trade.orderStatus.status
            if status and s != status:
                continue
            results.append(
                BrokerOrderStatus(
                    client_order_id=trade.order.orderRef or "",
                    broker_order_id=str(trade.order.orderId),
                    state=s,
                    filled_qty=Decimal(str(trade.orderStatus.filled)),
                    avg_fill_price=(
                        Decimal(str(trade.orderStatus.avgFillPrice))
                        if trade.orderStatus.avgFillPrice
                        else None
                    ),
                )
            )
        return results

    async def get_positions(self) -> list[BrokerPosition]:
        """Get all positions from IBKR."""
        await self._ensure_connected()
        positions = self._ib.positions()
        return [
            BrokerPosition(
                symbol=p.contract.symbol,
                qty=Decimal(str(p.position)),
                avg_cost=Decimal(str(p.avgCost)),
            )
            for p in positions
        ]

    async def get_fills(self, since: datetime | None = None) -> list[BrokerFill]:
        """Get fills from IBKR."""
        await self._ensure_connected()
        fills: list[BrokerFill] = []
        for trade in self._ib.trades():
            for fill in trade.fills:
                fill_time = fill.time if hasattr(fill, "time") else datetime.now(UTC)
                if since and fill_time < since:
                    continue
                fills.append(
                    BrokerFill(
                        broker_fill_id=str(fill.execution.execId),
                        broker_order_id=str(trade.order.orderId),
                        client_order_id=trade.order.orderRef or "",
                        symbol=fill.contract.symbol,
                        side=(OrderSide.BUY if fill.execution.side == "BOT" else OrderSide.SELL),
                        qty=Decimal(str(fill.execution.shares)),
                        price=Decimal(str(fill.execution.price)),
                        fees=Decimal(str(fill.commissionReport.commission))
                        if fill.commissionReport
                        else Decimal("0"),
                        occurred_at=fill_time,
                    )
                )
        return fills

    async def close(self) -> None:
        """Disconnect from TWS/Gateway."""
        if self._connected:
            self._ib.disconnect()
            self._connected = False
