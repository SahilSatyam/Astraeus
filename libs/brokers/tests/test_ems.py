"""Tests for the Execution Management System."""

from __future__ import annotations

from decimal import Decimal

import pytest

from astraeus_brokers.base import BrokerOrder, OrderSide, OrderType, TimeInForce
from astraeus_brokers.binance import BinancePaperAdapter
from astraeus_brokers.ems import BrokerNotConfiguredError, ExecutionManagementSystem


@pytest.fixture
def ems() -> ExecutionManagementSystem:
    e = ExecutionManagementSystem(default_broker="paper-1")
    e.register_adapter("paper-1", BinancePaperAdapter())
    e.register_adapter("paper-2", BinancePaperAdapter())
    return e


def _order(client_id: str = "ems-001", symbol: str = "AAPL") -> BrokerOrder:
    return BrokerOrder(
        client_order_id=client_id,
        symbol=symbol,
        side=OrderSide.BUY,
        qty=Decimal("100"),
        order_type=OrderType.MARKET,
        limit_price=Decimal("150"),
        tif=TimeInForce.DAY,
    )


@pytest.mark.unit
class TestEMS:
    async def test_submit_to_default_broker(self, ems: ExecutionManagementSystem) -> None:
        status = await ems.submit_order(_order())
        assert status.state == "filled"
        assert status.broker_order_id is not None

    async def test_submit_to_explicit_broker(self, ems: ExecutionManagementSystem) -> None:
        status = await ems.submit_order(_order(client_id="ems-002"), broker="paper-2")
        assert status.state == "filled"

    async def test_symbol_routing(self, ems: ExecutionManagementSystem) -> None:
        ems.set_symbol_route("BTCUSD", "paper-2")
        status = await ems.submit_order(_order(client_id="ems-003", symbol="BTCUSD"))
        assert status.state == "filled"

    async def test_broker_not_configured_raises(self, ems: ExecutionManagementSystem) -> None:
        with pytest.raises(BrokerNotConfiguredError):
            await ems.submit_order(_order(), broker="nonexistent")

    async def test_available_brokers(self, ems: ExecutionManagementSystem) -> None:
        assert "paper-1" in ems.available_brokers
        assert "paper-2" in ems.available_brokers

    async def test_get_positions(self, ems: ExecutionManagementSystem) -> None:
        await ems.submit_order(_order(client_id="pos-ems"))
        positions = await ems.get_positions(broker="paper-1")
        assert len(positions) == 1

    async def test_close_all(self, ems: ExecutionManagementSystem) -> None:
        # Should not raise
        await ems.close_all()
