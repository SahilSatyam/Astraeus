"""Human-in-the-Loop (HITL) queue — pause/resume for agent workflows.

Triggers: risk breach, compliance hit, confidence floor not met,
injection attempt, numerical claim without citation, cost overrun,
schema repair exhausted.

State machine: pending → claimed → (approved | rejected | edited)
               pending → expired (TTL hit)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger("astraeus.agent_runtime.hitl")


class HITLStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
    EXPIRED = "expired"


class HITLTrigger(StrEnum):
    RISK_BREACH = "risk_breach"
    COMPLIANCE_HIT = "compliance_hit"
    CONFIDENCE_FLOOR = "confidence_floor"
    INJECTION_DETECTED = "injection_detected"
    MISSING_CITATION = "missing_citation"
    COST_OVERRUN = "cost_overrun"
    REPAIR_EXHAUSTED = "repair_exhausted"


@dataclass(slots=True)
class HITLItem:
    """A single item in the HITL queue."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    run_id: uuid.UUID | None = None
    workflow_key: str = ""
    triggered_by: str = ""
    reason: dict[str, Any] = field(default_factory=dict)
    agent_state: dict[str, Any] = field(default_factory=dict)
    candidate_output: dict[str, Any] | None = None
    priority: int = 5  # 1=highest, 10=lowest
    status: HITLStatus = HITLStatus.PENDING
    claimed_by: uuid.UUID | None = None
    claimed_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution: dict[str, Any] | None = None
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(tz=UTC) + timedelta(hours=24)
    )
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


class HITLQueue:
    """In-memory HITL queue (backed by Postgres in production).

    Provides the state machine for pause/resume of agent workflows.
    """

    def __init__(self) -> None:
        self._items: dict[uuid.UUID, HITLItem] = {}

    def submit(
        self,
        run_id: uuid.UUID,
        workflow_key: str,
        triggered_by: HITLTrigger | str,
        reason: dict[str, Any],
        agent_state: dict[str, Any] | None = None,
        candidate_output: dict[str, Any] | None = None,
        priority: int = 5,
        ttl_hours: int = 24,
    ) -> HITLItem:
        """Submit a new item to the HITL queue."""
        item = HITLItem(
            run_id=run_id,
            workflow_key=workflow_key,
            triggered_by=str(triggered_by),
            reason=reason,
            agent_state=agent_state or {},
            candidate_output=candidate_output,
            priority=priority,
            expires_at=datetime.now(tz=UTC) + timedelta(hours=ttl_hours),
        )
        self._items[item.id] = item

        logger.info(
            "hitl_item_submitted",
            item_id=str(item.id),
            run_id=str(run_id),
            trigger=str(triggered_by),
            priority=priority,
        )
        return item

    def get(self, item_id: uuid.UUID) -> HITLItem | None:
        """Get an item by ID."""
        return self._items.get(item_id)

    def list_pending(self, workflow_key: str | None = None) -> list[HITLItem]:
        """List pending items, optionally filtered by workflow."""
        self._expire_stale()
        items = [
            item for item in self._items.values()
            if item.status == HITLStatus.PENDING
        ]
        if workflow_key:
            items = [i for i in items if i.workflow_key == workflow_key]
        return sorted(items, key=lambda i: (i.priority, i.created_at))

    def claim(self, item_id: uuid.UUID, claimed_by: uuid.UUID) -> bool:
        """Claim a pending item for review."""
        item = self._items.get(item_id)
        if item is None or item.status != HITLStatus.PENDING:
            return False

        item.status = HITLStatus.CLAIMED
        item.claimed_by = claimed_by
        item.claimed_at = datetime.now(tz=UTC)

        logger.info("hitl_item_claimed", item_id=str(item_id), claimed_by=str(claimed_by))
        return True

    def approve(self, item_id: uuid.UUID, resolution: dict[str, Any] | None = None) -> bool:
        """Approve a claimed item — orchestrator resumes from checkpoint."""
        item = self._items.get(item_id)
        if item is None or item.status != HITLStatus.CLAIMED:
            return False

        item.status = HITLStatus.APPROVED
        item.resolved_at = datetime.now(tz=UTC)
        item.resolution = resolution or {"action": "approved"}

        logger.info("hitl_item_approved", item_id=str(item_id))
        return True

    def reject(self, item_id: uuid.UUID, reason: str = "") -> bool:
        """Reject a claimed item — run terminates."""
        item = self._items.get(item_id)
        if item is None or item.status != HITLStatus.CLAIMED:
            return False

        item.status = HITLStatus.REJECTED
        item.resolved_at = datetime.now(tz=UTC)
        item.resolution = {"action": "rejected", "reason": reason}

        logger.info("hitl_item_rejected", item_id=str(item_id), reason=reason)
        return True

    def edit(self, item_id: uuid.UUID, edited_output: dict[str, Any]) -> bool:
        """Edit a claimed item — orchestrator resumes with human-edited output."""
        item = self._items.get(item_id)
        if item is None or item.status != HITLStatus.CLAIMED:
            return False

        item.status = HITLStatus.EDITED
        item.resolved_at = datetime.now(tz=UTC)
        item.resolution = {"action": "edited", "output": edited_output}

        logger.info("hitl_item_edited", item_id=str(item_id))
        return True

    def _expire_stale(self) -> None:
        """Expire items past their TTL."""
        now = datetime.now(tz=UTC)
        for item in self._items.values():
            if item.status == HITLStatus.PENDING and item.expires_at < now:
                item.status = HITLStatus.EXPIRED
                logger.info("hitl_item_expired", item_id=str(item.id))
