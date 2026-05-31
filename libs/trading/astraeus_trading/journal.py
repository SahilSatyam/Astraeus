"""Append-only trade journal.

The trade journal is an immutable audit log. Every order state transition, fill,
override, and kill-switch flip is recorded. The journal enforces gapless sequence
numbers per account and is protected at the DB level (REVOKE UPDATE, DELETE).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class JournalKind(StrEnum):
    """Types of journal entries."""

    ORDER_STATE = "order_state"
    FILL = "fill"
    OVERRIDE = "override"
    KILL_SWITCH_FLIP = "kill_switch_flip"
    RISK_REJECTION = "risk_rejection"
    RECON_DRIFT = "recon_drift"


class JournalEntry(BaseModel):
    """A single immutable journal entry.

    Attributes:
        account_id: The trading account.
        kind: Category of the event.
        payload: Structured event data.
        written_at: Timestamp of journal write.
    """

    account_id: str
    kind: JournalKind
    payload: dict[str, Any]
    written_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {"frozen": True}
