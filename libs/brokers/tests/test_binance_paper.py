"""Tests for the Binance paper trading adapter."""

from __future__ import annotations

from decimal import Decimal

import pytest
from astraeus_brokers.base import BrokerOrder, OrderSide, OrderType, TimeInForce
from astraeus_brokers.binance import BinancePaperAdapter


@pytest.fixture
def adapter() -> BinancePaperAdapter:
    return BinancePaperAdapter()


def _market_order(client_id: str = "test-001", symbol: str = "BTCUSD") -> BrokerOrder:
    return BrokerOrder(
        client_order_id=client_id,
        symbol=symbol,
        side=OrderSide.BUY,
        qty=Decimal("1.5"),
        order_type=OrderType.MARKET,
        limit_price=Decimal("50000"),
        tif=TimeInForce.DAY,
    )


def _limit_order(client_id: str = "test-002", symbol: str = "ETHUSD") -> BrokerOrder:
    return BrokerOrder(
        client_order_id=client_id,
        symbol=symbol,
        side=OrderSide.BUY,
        qty=Decimal("10"),
        order_type=OrderType.LIMIT,
        limit_price=Decimal("3000"),
        tif=TimeInForce.GTC,
    )


@pytest.mark.unit
class TestBinancePaperAdapter:
    async def test_name(self, adapter: BinancePaperAdapter) -> None:
        assert adapter.name == "binance-paper"

    async def test_market_order_fills_immediately(self, adapter: BinancePaperAdapter) -> None:
        order = _market_order()
        status = await adapter.submit_order(order)
        assert status.state == "filled"
        assert status.filled_qty == Decimal("1.5")
        assert status.broker_order_id is not None

    async def test_limit_order_stays_open(self, adapter: BinancePaperAdapter) -> None:
        order = _limit_order()
        status = await adapter.submit_order(order)
        assert status.state == "open"
        assert status.filled_qty == Decimal("0")

    async def test_idempotent_submission(self, adapter: BinancePaperAdapter) -> None:
        order = _market_order(client_id="idem-001")
        status1 = await adapter.submit_order(order)
        status2 = await adapter.submit_order(order)
        assert status1.broker_order_id == status2.broker_order_id

    async def test_cancel_open_order(self, adapter: BinancePaperAdapter) -> None:
        order = _limit_order(client_id="cancel-001")
        status = await adapter.submit_order(order)
        cancel_status = await adapter.cancel_order(status.broker_order_id)
        assert cancel_status.state == "cancelled"

    async def test_positions_updated_on_fill(self, adapter: BinancePaperAdapter) -> None:
        order = _market_order(client_id="pos-001", symbol="BTCUSD")
        await adapter.submit_order(order)
        positions = await adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "BTCUSD"
        assert positions[0].qty == Decimal("1.5")

    async def test_get_fills(self, adapter: BinancePaperAdapter) -> None:
        await adapter.submit_order(_market_order(client_id="fill-001"))
        fills = await adapter.get_fills()
        assert len(fills) == 1
        assert fills[0].symbol == "BTCUSD"
        assert fills[0].qty == Decimal("1.5")

    async def test_get_orders(self, adapter: BinancePaperAdapter) -> None:
        await adapter.submit_order(_market_order(client_id="list-001"))
        await adapter.submit_order(_limit_order(client_id="list-002"))
        all_orders = await adapter.get_orders()
        assert len(all_orders) == 2
        open_orders = await adapter.get_orders(status="open")
        assert len(open_orders) == 1
