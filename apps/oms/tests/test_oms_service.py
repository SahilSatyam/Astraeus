"""Tests for OMS service using a mock broker adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from astraeus_brokers.base import BrokerAdapter, BrokerOrder, BrokerOrderStatus
from astraeus_oms.schemas import SubmitOrderRequest
from astraeus_oms.service import KillSwitchActive, OMSService, OrderAlreadyExists
from astraeus_trading.statemachine import OrderState


class MockBrokerAdapter:
    """In-memory mock broker for testing."""

    def __init__(self) -> None:
        self._orders: dict[str, BrokerOrderStatus] = {}
        self._next_id = 1

    @property
    def name(self) -> str:
        return "mock-paper"

    async def submit_order(self, order: BrokerOrder) -> BrokerOrderStatus:
        broker_id = f"broker-{self._next_id}"
        self._next_id += 1
        status = BrokerOrderStatus(
            client_order_id=order.client_order_id,
            broker_order_id=broker_id,
            state="accepted",
            filled_qty=Decimal("0"),
            submitted_at=datetime.now(timezone.utc),
        )
        self._orders[broker_id] = status
        return status

    async def cancel_order(self, broker_order_id: str) -> BrokerOrderStatus:
        status = self._orders.get(broker_order_id)
        if status:
            return BrokerOrderStatus(
                client_order_id=status.client_order_id,
                broker_order_id=broker_order_id,
                state="cancelled",
            )
        return BrokerOrderStatus(
            client_order_id="",
            broker_order_id=broker_order_id,
            state="unknown",
        )

    async def get_order_status(self, broker_order_id: str) -> BrokerOrderStatus:
        return self._orders.get(
            broker_order_id,
            BrokerOrderStatus(
                client_order_id="", broker_order_id=broker_order_id, state="unknown"
            ),
        )

    async def get_orders(self, status=None):
        return list(self._orders.values())

    async def get_positions(self):
        return []

    async def get_fills(self, since=None):
        return []

    async def close(self):
        pass


@pytest.fixture
def mock_broker() -> MockBrokerAdapter:
    return MockBrokerAdapter()


def _submit_request(client_order_id: str = "test-key-001") -> SubmitOrderRequest:
    return SubmitOrderRequest(
        client_order_id=client_order_id,
        account_id="test-account",
        strategy_id="momentum",
        symbol="AAPL",
        side="buy",
        qty=Decimal("100"),
        order_type="market",
        tif="DAY",
    )
