"""OMS core service — order lifecycle management.

This service owns the order state machine, event sourcing, and idempotent
submission logic. It coordinates between the pre-trade risk gateway, the
broker adapters (EMS), and the trade journal.

Architectural rule: NO LLM/agent imports here. This is enforced at CI.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from astraeus_brokers.base import BrokerAdapter, BrokerOrder, OrderSide, OrderType, TimeInForce
from astraeus_trading.events import EventType, OrderEvent
from astraeus_trading.journal import JournalEntry, JournalKind
from astraeus_trading.models import (
    FillModel,
    KillSwitchStateModel,
    OrderEventModel,
    OrderModel,
    TradeJournalModel,
)
from astraeus_trading.statemachine import OrderState, OrderStateMachine

from astraeus_oms.schemas import OrderResponse, SubmitOrderRequest


class KillSwitchActive(Exception):
    """Raised when a kill switch is armed for the relevant scope."""

    def __init__(self, scope: str, reason: str = "") -> None:
        self.scope = scope
        self.reason = reason
        super().__init__(f"Kill switch armed for scope={scope}: {reason}")


class OrderAlreadyExists(Exception):
    """Raised when an order with the same client_order_id already exists (idempotent return)."""

    def __init__(self, existing_order: OrderResponse) -> None:
        self.existing_order = existing_order
        super().__init__(f"Order already exists: {existing_order.client_order_id}")


class OMSService:
    """Order Management System service.

    Coordinates order submission, state transitions, and event recording.
    """

    def __init__(
        self,
        session: AsyncSession,
        broker: BrokerAdapter,
    ) -> None:
        self._session = session
        self._broker = broker

    async def submit_order(self, request: SubmitOrderRequest) -> OrderResponse:
        """Submit a new order. Idempotent on client_order_id.

        Flow:
        1. Check kill switches (global, account, strategy).
        2. Check for existing order with same client_order_id (idempotent return).
        3. Create order in NEW state.
        4. Record NEW event.
        5. Transition to PENDING_NEW.
        6. Submit to broker via EMS.
        7. Transition to SUBMITTED (or REJECTED).
        8. Record events and journal entries.
        """
        # 1. Check kill switches
        await self._check_kill_switches(request.account_id, request.strategy_id)

        # 2. Idempotency check
        existing = await self._find_by_client_order_id(request.client_order_id)
        if existing:
            raise OrderAlreadyExists(self._to_response(existing))

        # 3. Create order
        now = datetime.now(timezone.utc)
        order_id = str(uuid.uuid4())
        order = OrderModel(
            order_id=order_id,
            client_order_id=request.client_order_id,
            account_id=request.account_id,
            strategy_id=request.strategy_id,
            rec_id=request.rec_id,
            decision_id=request.decision_id,
            symbol=request.symbol,
            side=request.side,
            qty=request.qty,
            order_type=request.order_type,
            limit_price=request.limit_price,
            tif=request.tif,
            state=OrderState.NEW,
            submitted_to=self._broker.name,
            created_at=now,
            updated_at=now,
        )
        self._session.add(order)

        # 4. Record NEW event
        await self._record_event(order_id, EventType.NEW, {}, now)

        # 5. Transition to PENDING_NEW
        sm = OrderStateMachine(OrderState.NEW)
        sm.transition(OrderState.PENDING_NEW)
        order.state = sm.state
        order.updated_at = datetime.now(timezone.utc)
        await self._record_event(order_id, EventType.PENDING_NEW, {}, order.updated_at)

        # 6. Submit to broker
        broker_order = BrokerOrder(
            client_order_id=request.client_order_id,
            symbol=request.symbol,
            side=OrderSide(request.side),
            qty=request.qty,
            order_type=OrderType(request.order_type),
            limit_price=request.limit_price,
            tif=TimeInForce(request.tif),
        )

        try:
            status = await self._broker.submit_order(broker_order)
        except Exception as e:
            # Broker submission failed — mark as REJECTED
            sm.transition(OrderState.REJECTED)
            order.state = sm.state
            order.updated_at = datetime.now(timezone.utc)
            await self._record_event(
                order_id,
                EventType.REJECTED,
                {"reason": str(e)},
                order.updated_at,
            )
            await self._journal(
                request.account_id,
                JournalKind.ORDER_STATE,
                {"order_id": order_id, "state": "rejected", "reason": str(e)},
            )
            await self._session.flush()
            return self._to_response(order)

        # 7. Transition to SUBMITTED
        sm.transition(OrderState.SUBMITTED)
        order.state = sm.state
        order.broker_order_id = status.broker_order_id
        order.updated_at = datetime.now(timezone.utc)
        await self._record_event(
            order_id,
            EventType.SUBMITTED,
            {
                "broker_order_id": status.broker_order_id,
                "broker_state": status.state,
            },
            order.updated_at,
        )

        # 8. Journal
        await self._journal(
            request.account_id,
            JournalKind.ORDER_STATE,
            {
                "order_id": order_id,
                "state": "submitted",
                "broker": self._broker.name,
                "broker_order_id": status.broker_order_id,
            },
        )

        await self._session.flush()
        return self._to_response(order)

    async def cancel_order(self, order_id: str, reason: str = "") -> OrderResponse:
        """Request cancellation of an order."""
        order = await self._get_order(order_id)
        sm = OrderStateMachine(OrderState(order.state))

        if not sm.can_transition(OrderState.CANCELLED):
            msg = f"Cannot cancel order in state {order.state}"
            raise ValueError(msg)

        # Request cancel from broker
        if order.broker_order_id:
            await self._broker.cancel_order(order.broker_order_id)

        sm.transition(OrderState.CANCELLED)
        order.state = sm.state
        order.updated_at = datetime.now(timezone.utc)

        await self._record_event(
            order_id,
            EventType.CANCELLED,
            {"reason": reason},
            order.updated_at,
        )
        await self._journal(
            order.account_id,
            JournalKind.ORDER_STATE,
            {"order_id": order_id, "state": "cancelled", "reason": reason},
        )

        await self._session.flush()
        return self._to_response(order)

    async def get_order(self, order_id: str) -> OrderResponse:
        """Get an order by ID."""
        order = await self._get_order(order_id)
        return self._to_response(order)

    async def apply_fill(
        self,
        order_id: str,
        qty: Decimal,
        price: Decimal,
        fees: Decimal = Decimal("0"),
        broker_fill_id: str | None = None,
        venue: str | None = None,
        occurred_at: datetime | None = None,
    ) -> OrderResponse:
        """Apply a fill to an order, transitioning state as needed."""
        order = await self._get_order(order_id)
        sm = OrderStateMachine(OrderState(order.state))
        fill_time = occurred_at or datetime.now(timezone.utc)

        # Determine if this is a partial or full fill
        filled_so_far = await self._total_filled_qty(order_id)
        total_after = filled_so_far + qty
        order_qty = Decimal(str(order.qty))

        if total_after >= order_qty:
            target_state = OrderState.FILLED
            event_type = EventType.FILLED
        else:
            target_state = OrderState.PARTIAL_FILL
            event_type = EventType.PARTIAL_FILL

        sm.transition(target_state)
        order.state = sm.state
        order.updated_at = datetime.now(timezone.utc)

        # Record fill
        fill = FillModel(
            fill_id=str(uuid.uuid4()),
            order_id=order_id,
            qty=qty,
            price=price,
            fees=fees,
            venue=venue,
            broker_fill_id=broker_fill_id,
            occurred_at=fill_time,
        )
        self._session.add(fill)

        await self._record_event(
            order_id,
            event_type,
            {
                "qty": str(qty),
                "price": str(price),
                "fees": str(fees),
                "broker_fill_id": broker_fill_id,
                "total_filled": str(total_after),
            },
            fill_time,
        )

        await self._journal(
            order.account_id,
            JournalKind.FILL,
            {
                "order_id": order_id,
                "fill_qty": str(qty),
                "fill_price": str(price),
                "total_filled": str(total_after),
                "order_qty": str(order_qty),
            },
        )

        await self._session.flush()
        return self._to_response(order)

    # --- Internal helpers ---

    async def _check_kill_switches(self, account_id: str, strategy_id: str) -> None:
        """Check if any relevant kill switch is armed."""
        scopes = ["global", f"account:{account_id}", f"strategy:{strategy_id}"]
        stmt = select(KillSwitchStateModel).where(
            KillSwitchStateModel.scope.in_(scopes),
            KillSwitchStateModel.armed.is_(True),
        )
        result = await self._session.execute(stmt)
        armed = result.scalars().first()
        if armed:
            raise KillSwitchActive(armed.scope, armed.reason or "")

    async def _find_by_client_order_id(self, client_order_id: str) -> OrderModel | None:
        """Find an existing order by client_order_id."""
        stmt = select(OrderModel).where(OrderModel.client_order_id == client_order_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def _get_order(self, order_id: str) -> OrderModel:
        """Get an order by ID or raise."""
        stmt = select(OrderModel).where(OrderModel.order_id == order_id)
        result = await self._session.execute(stmt)
        order = result.scalars().first()
        if not order:
            msg = f"Order not found: {order_id}"
            raise ValueError(msg)
        return order

    async def _total_filled_qty(self, order_id: str) -> Decimal:
        """Sum of all fill quantities for an order."""
        from sqlalchemy import func as sqlfunc

        stmt = select(sqlfunc.coalesce(sqlfunc.sum(FillModel.qty), 0)).where(
            FillModel.order_id == order_id
        )
        result = await self._session.execute(stmt)
        return Decimal(str(result.scalar_one()))

    async def _record_event(
        self,
        order_id: str,
        event_type: EventType,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> None:
        """Append an event to the order event log."""
        event = OrderEventModel(
            order_id=order_id,
            event_type=event_type.value,
            payload=payload,
            occurred_at=occurred_at,
            source="oms",
        )
        self._session.add(event)

    async def _journal(
        self,
        account_id: str,
        kind: JournalKind,
        payload: dict[str, Any],
    ) -> None:
        """Write to the append-only trade journal."""
        entry = TradeJournalModel(
            account_id=account_id,
            kind=kind.value,
            payload=payload,
        )
        self._session.add(entry)

    @staticmethod
    def _to_response(order: OrderModel) -> OrderResponse:
        return OrderResponse(
            order_id=order.order_id,
            client_order_id=order.client_order_id,
            account_id=order.account_id,
            strategy_id=order.strategy_id,
            symbol=order.symbol,
            side=order.side,
            qty=Decimal(str(order.qty)),
            order_type=order.order_type,
            limit_price=Decimal(str(order.limit_price)) if order.limit_price else None,
            tif=order.tif,
            state=order.state,
            submitted_to=order.submitted_to,
            broker_order_id=order.broker_order_id,
            created_at=order.created_at,
            updated_at=order.updated_at,
        )
