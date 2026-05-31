"""Order event schemas for event sourcing.

Every order state change is recorded as an immutable event. The order's current
state is the fold of its event stream. This enables crash recovery, audit, and
replay.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EventType(StrEnum):
    """Types of order events."""

    NEW = "new"
    PENDING_NEW = "pending_new"
    SUBMITTED = "submitted"
    PARTIAL_FILL = "partial_fill"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OrderEvent(BaseModel):
    """Immutable order event.

    Attributes:
        event_id: Unique event identifier.
        order_id: The order this event belongs to.
        event_type: What happened.
        payload: Broker-specific or context data (fill qty, reject reason, etc.).
        occurred_at: When the event actually happened (broker timestamp).
        received_at: When we recorded it.
        source: Origin of the event (oms, broker, recon).
    """

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    order_id: str
    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str = "oms"

    model_config = {"frozen": True}
