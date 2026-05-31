"""Unit tests for the HITL queue."""

from __future__ import annotations

import uuid

from astraeus_agent_runtime.hitl import HITLQueue, HITLStatus, HITLTrigger


class TestHITLQueue:
    """Test HITL queue state machine."""

    def _make_queue_with_item(self) -> tuple[HITLQueue, uuid.UUID]:
        queue = HITLQueue()
        run_id = uuid.uuid4()
        item = queue.submit(
            run_id=run_id,
            workflow_key="trade_thesis",
            triggered_by=HITLTrigger.RISK_BREACH,
            reason={"check": "var", "value": 0.12, "threshold": 0.10},
        )
        return queue, item.id

    def test_submit_creates_pending_item(self) -> None:
        queue = HITLQueue()
        run_id = uuid.uuid4()
        item = queue.submit(
            run_id=run_id,
            workflow_key="trade_thesis",
            triggered_by=HITLTrigger.RISK_BREACH,
            reason={"detail": "VaR breach"},
        )
        assert item.status == HITLStatus.PENDING
        assert item.run_id == run_id
        assert item.workflow_key == "trade_thesis"

    def test_list_pending(self) -> None:
        queue = HITLQueue()
        queue.submit(
            run_id=uuid.uuid4(),
            workflow_key="trade_thesis",
            triggered_by=HITLTrigger.RISK_BREACH,
            reason={},
        )
        queue.submit(
            run_id=uuid.uuid4(),
            workflow_key="daily_brief",
            triggered_by=HITLTrigger.COMPLIANCE_HIT,
            reason={},
        )
        pending = queue.list_pending()
        assert len(pending) == 2

    def test_list_pending_filtered_by_workflow(self) -> None:
        queue = HITLQueue()
        queue.submit(
            run_id=uuid.uuid4(), workflow_key="trade_thesis", triggered_by="test", reason={}
        )
        queue.submit(
            run_id=uuid.uuid4(), workflow_key="daily_brief", triggered_by="test", reason={}
        )
        pending = queue.list_pending(workflow_key="trade_thesis")
        assert len(pending) == 1

    def test_claim_transitions_to_claimed(self) -> None:
        queue, item_id = self._make_queue_with_item()
        reviewer = uuid.uuid4()
        success = queue.claim(item_id, reviewer)
        assert success is True
        item = queue.get(item_id)
        assert item is not None
        assert item.status == HITLStatus.CLAIMED
        assert item.claimed_by == reviewer

    def test_claim_non_pending_fails(self) -> None:
        queue, item_id = self._make_queue_with_item()
        reviewer = uuid.uuid4()
        queue.claim(item_id, reviewer)
        # Try to claim again
        success = queue.claim(item_id, uuid.uuid4())
        assert success is False

    def test_approve_transitions_to_approved(self) -> None:
        queue, item_id = self._make_queue_with_item()
        queue.claim(item_id, uuid.uuid4())
        success = queue.approve(item_id)
        assert success is True
        item = queue.get(item_id)
        assert item is not None
        assert item.status == HITLStatus.APPROVED
        assert item.resolved_at is not None

    def test_reject_transitions_to_rejected(self) -> None:
        queue, item_id = self._make_queue_with_item()
        queue.claim(item_id, uuid.uuid4())
        success = queue.reject(item_id, reason="Not appropriate")
        assert success is True
        item = queue.get(item_id)
        assert item is not None
        assert item.status == HITLStatus.REJECTED
        assert item.resolution is not None
        assert item.resolution["reason"] == "Not appropriate"

    def test_edit_transitions_to_edited(self) -> None:
        queue, item_id = self._make_queue_with_item()
        queue.claim(item_id, uuid.uuid4())
        edited = {"findings": [{"claim": "Edited claim"}]}
        success = queue.edit(item_id, edited)
        assert success is True
        item = queue.get(item_id)
        assert item is not None
        assert item.status == HITLStatus.EDITED
        assert item.resolution is not None
        assert item.resolution["output"] == edited

    def test_approve_unclaimed_fails(self) -> None:
        queue, item_id = self._make_queue_with_item()
        success = queue.approve(item_id)
        assert success is False

    def test_priority_ordering(self) -> None:
        queue = HITLQueue()
        queue.submit(run_id=uuid.uuid4(), workflow_key="w", triggered_by="t", reason={}, priority=5)
        queue.submit(run_id=uuid.uuid4(), workflow_key="w", triggered_by="t", reason={}, priority=1)
        queue.submit(run_id=uuid.uuid4(), workflow_key="w", triggered_by="t", reason={}, priority=3)
        pending = queue.list_pending()
        priorities = [item.priority for item in pending]
        assert priorities == sorted(priorities)
