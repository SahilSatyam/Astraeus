"""OMS API routes.

Endpoints:
    POST /oms/orders          — Submit order (idempotent)
    POST /oms/orders/{id}/cancel — Cancel order
    GET  /oms/orders/{id}     — Get order
    GET  /oms/orders          — List orders
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from astraeus_oms.dependencies import get_broker, get_session
from astraeus_oms.schemas import (
    CancelOrderRequest,
    OrderResponse,
    SubmitOrderRequest,
)
from astraeus_oms.service import KillSwitchActive, OMSService, OrderAlreadyExists

router = APIRouter(prefix="/oms", tags=["oms"])


@router.post("/orders", response_model=OrderResponse, status_code=201)
async def submit_order(
    request: SubmitOrderRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    broker: Annotated[object, Depends(get_broker)],
) -> OrderResponse:
    """Submit a new order. Idempotent on client_order_id."""
    svc = OMSService(session=session, broker=broker)
    try:
        return await svc.submit_order(request)
    except OrderAlreadyExists as e:
        # Idempotent: return existing order with 200
        return e.existing_order
    except KillSwitchActive as e:
        raise HTTPException(status_code=423, detail=f"Kill switch armed: {e.scope}") from e


@router.post("/orders/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(
    order_id: str,
    body: CancelOrderRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    broker: Annotated[object, Depends(get_broker)],
) -> OrderResponse:
    """Cancel an order."""
    svc = OMSService(session=session, broker=broker)
    try:
        return await svc.cancel_order(order_id, reason=body.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    broker: Annotated[object, Depends(get_broker)],
) -> OrderResponse:
    """Get a single order by ID."""
    svc = OMSService(session=session, broker=broker)
    try:
        return await svc.get_order(order_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/orders", response_model=list[OrderResponse])
async def list_orders(
    session: Annotated[AsyncSession, Depends(get_session)],
    broker: Annotated[object, Depends(get_broker)],
    account_id: Annotated[str | None, Query()] = None,
    strategy_id: Annotated[str | None, Query()] = None,
) -> list[OrderResponse]:
    """List orders with optional filters."""
    from sqlalchemy import select

    from astraeus_trading.models import OrderModel

    stmt = select(OrderModel)
    if account_id:
        stmt = stmt.where(OrderModel.account_id == account_id)
    if strategy_id:
        stmt = stmt.where(OrderModel.strategy_id == strategy_id)
    stmt = stmt.order_by(OrderModel.created_at.desc()).limit(100)

    result = await session.execute(stmt)
    orders = result.scalars().all()
    return [OMSService._to_response(o) for o in orders]
