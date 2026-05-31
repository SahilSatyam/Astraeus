"""Execution Management System — broker routing and adapter management.

The EMS sits between the OMS and the broker adapters. It handles:
- Broker selection (which adapter to use for a given order)
- Smart routing (single venue per symbol for now)
- Adapter lifecycle management
- Broker-specific quirk isolation

The OMS sends a BrokerOrder; the EMS picks the right adapter and submits.
"""

from __future__ import annotations

import logging
from typing import Any

from astraeus_brokers.base import (
    BrokerAdapter,
    BrokerFill,
    BrokerOrder,
    BrokerOrderStatus,
    BrokerPosition,
)

logger = logging.getLogger(__name__)


class BrokerNotConfiguredError(Exception):
    """Raised when no broker adapter is available for the requested route."""

    def __init__(self, broker_name: str) -> None:
        self.broker_name = broker_name
        super().__init__(f"No broker adapter configured for: {broker_name}")


class ExecutionManagementSystem:
    """Broker routing and adapter management.

    Usage::

        ems = ExecutionManagementSystem()
        ems.register_adapter("alpaca-paper", alpaca_adapter)
        ems.register_adapter("ibkr-paper", ibkr_adapter)

        # Route by explicit broker name
        status = await ems.submit_order(order, broker="alpaca-paper")

        # Or use default routing
        status = await ems.submit_order(order)
    """

    def __init__(self, default_broker: str = "alpaca-paper") -> None:
        self._adapters: dict[str, BrokerAdapter] = {}
        self._default_broker = default_broker
        # Symbol-to-broker routing overrides
        self._symbol_routes: dict[str, str] = {}

    def register_adapter(self, name: str, adapter: BrokerAdapter) -> None:
        """Register a broker adapter."""
        self._adapters[name] = adapter
        logger.info("Registered broker adapter", extra={"broker": name})

    def set_symbol_route(self, symbol: str, broker: str) -> None:
        """Set a routing override for a specific symbol."""
        self._symbol_routes[symbol] = broker

    def get_adapter(self, broker: str | None = None) -> BrokerAdapter:
        """Get a broker adapter by name, or the default."""
        name = broker or self._default_broker
        adapter = self._adapters.get(name)
        if adapter is None:
            raise BrokerNotConfiguredError(name)
        return adapter

    @property
    def available_brokers(self) -> list[str]:
        """List registered broker names."""
        return list(self._adapters.keys())

    async def submit_order(
        self, order: BrokerOrder, broker: str | None = None
    ) -> BrokerOrderStatus:
        """Submit an order via the appropriate broker adapter.

        Routing priority:
        1. Explicit broker parameter
        2. Symbol-specific route
        3. Default broker
        """
        target = broker or self._symbol_routes.get(order.symbol) or self._default_broker
        adapter = self.get_adapter(target)

        logger.info(
            "Submitting order via EMS",
            extra={
                "broker": target,
                "symbol": order.symbol,
                "side": order.side,
                "qty": str(order.qty),
                "client_order_id": order.client_order_id,
            },
        )

        return await adapter.submit_order(order)

    async def cancel_order(
        self, broker_order_id: str, broker: str | None = None
    ) -> BrokerOrderStatus:
        """Cancel an order via the specified broker."""
        adapter = self.get_adapter(broker)
        return await adapter.cancel_order(broker_order_id)

    async def get_order_status(
        self, broker_order_id: str, broker: str | None = None
    ) -> BrokerOrderStatus:
        """Get order status from the specified broker."""
        adapter = self.get_adapter(broker)
        return await adapter.get_order_status(broker_order_id)

    async def get_positions(self, broker: str | None = None) -> list[BrokerPosition]:
        """Get positions from the specified broker."""
        adapter = self.get_adapter(broker)
        return await adapter.get_positions()

    async def get_fills(self, broker: str | None = None, since: Any = None) -> list[BrokerFill]:
        """Get fills from the specified broker."""
        adapter = self.get_adapter(broker)
        return await adapter.get_fills(since=since)

    async def close_all(self) -> None:
        """Close all broker adapter connections."""
        for name, adapter in self._adapters.items():
            try:
                await adapter.close()
            except Exception:
                logger.exception("Error closing broker adapter", extra={"broker": name})
