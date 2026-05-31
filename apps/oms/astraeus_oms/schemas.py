"""API request/response schemas for the OMS."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class SubmitOrderRequest(BaseModel):
    """Request to submit a new order."""

    client_order_id: str
    account_id: str
    strategy_id: str
    rec_id: str | None = None
    decision_id: str | None = None
    symbol: str
    side: str = Field(pattern=r"^(buy|sell)$")
    qty: Decimal
    order_type: str = Field(default="market", pattern=r"^(market|limit)$")
    limit_price: Decimal | None = None
    tif: str = Field(default="DAY", pattern=r"^(DAY|GTC)$")


class OrderResponse(BaseModel):
    """Order representation returned by the API."""

    order_id: str
    client_order_id: str
    account_id: str
    strategy_id: str
    symbol: str
    side: str
    qty: Decimal
    order_type: str
    limit_price: Decimal | None = None
    tif: str
    state: str
    submitted_to: str
    broker_order_id: str | None = None
    created_at: datetime
    updated_at: datetime


class CancelOrderRequest(BaseModel):
    """Request to cancel an order."""

    reason: str = ""


class OrderEventResponse(BaseModel):
    """Order event representation."""

    event_seq: int
    order_id: str
    event_type: str
    payload: dict
    occurred_at: datetime
    received_at: datetime
    source: str
