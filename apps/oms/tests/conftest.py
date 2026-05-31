"""OMS test fixtures."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from astraeus_brokers.base import (
    BrokerAdapter,
    BrokerFill,
    BrokerOrder,
    BrokerOrderStatus,
    BrokerPosition,
)


class MockBroker(BrokerAdapter):
    """In-memory mock broker for testing."""

    def __init__(self) -> None:
        self._orders: dict[str, BrokerOrderStatus] = {}
        self._should_reject = False
        self._reject_reason = ""

    @property
    def name(self) -> str:
        return "mock-broker"

    def set_reject(self, reason: str = "insufficient funds") -> None:
        self._should_reject = True
        self._reject_reason = reason

    def clear_reject(self) -> None:
        self._should_reject = False
        self._reject_reason = ""

    async def submit_order(self, order: BrokerOrder) -> BrokerOrderStatus:
        if self._should_reject:
            raise RuntimeError(self._reject_reason)

        status = BrokerOrderStatus(
            client_order_id=order.client_order_id,
            broker_order_id=f"BROKER-{order.client_order_id}",
            state="accepted",
            submitted_at=datetime.now(UTC),
        )
        self._orders[status.broker_order_id] = status
        return status

    async def cancel_order(self, broker_order_id: str) -> BrokerOrderStatus:
        status = self._orders.get(broker_order_id)
        if not status:
            raise ValueError(f"Order not found: {broker_order_id}")
        status = status.model_copy(update={"state": "cancelled"})
        self._orders[broker_order_id] = status
        return status

    async def get_order_status(self, broker_order_id: str) -> BrokerOrderStatus:
        status = self._orders.get(broker_order_id)
        if not status:
            raise ValueError(f"Order not found: {broker_order_id}")
        return status

    async def get_orders(self, status: str | None = None) -> list[BrokerOrderStatus]:
        orders = list(self._orders.values())
        if status:
            orders = [o for o in orders if o.state == status]
        return orders

    async def get_positions(self) -> list[BrokerPosition]:
        return []

    async def get_fills(self, since: datetime | None = None) -> list[BrokerFill]:
        return []

    async def close(self) -> None:
        pass


@pytest.fixture
def mock_broker() -> MockBroker:
    return MockBroker()


@pytest.fixture
def submit_order_request() -> dict:
    """Standard order submission payload."""
    return {
        "client_order_id": "test-order-001",
        "account_id": "acct-1",
        "strategy_id": "momentum_xs",
        "symbol": "AAPL",
        "side": "buy",
        "qty": "100",
        "order_type": "market",
        "tif": "DAY",
    }


@pytest.fixture
def limit_order_request() -> dict:
    """Limit order submission payload."""
    return {
        "client_order_id": "test-limit-001",
        "account_id": "acct-1",
        "strategy_id": "mean_revert",
        "symbol": "MSFT",
        "side": "sell",
        "qty": "50",
        "order_type": "limit",
        "limit_price": "425.50",
        "tif": "GTC",
    }
