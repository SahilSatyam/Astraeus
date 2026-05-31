"""Tests for order events."""

from __future__ import annotations

from datetime import datetime, timezone

from astraeus_trading.events import EventType, OrderEvent


class TestOrderEvent:
    """Unit tests for OrderEvent."""

    def test_create_event(self) -> None:
        event = OrderEvent(
            order_id="order-123",
            event_type=EventType.NEW,
            occurred_at=datetime.now(timezone.utc),
        )
        assert event.order_id == "order-123"
        assert event.event_type == EventType.NEW
        assert event.source == "oms"
        assert event.payload == {}

    def test_event_is_frozen(self) -> None:
        event = OrderEvent(
            order_id="order-123",
            event_type=EventType.SUBMITTED,
            occurred_at=datetime.now(timezone.utc),
        )
        # Pydantic frozen model should raise on mutation
        try:
            event.order_id = "other"  # type: ignore[misc]
            assert False, "Should have raised"
        except Exception:
            pass

    def test_event_with_payload(self) -> None:
        event = OrderEvent(
            order_id="order-123",
            event_type=EventType.PARTIAL_FILL,
            payload={"qty": "50", "price": "150.25"},
            occurred_at=datetime.now(timezone.utc),
            source="broker",
        )
        assert event.payload["qty"] == "50"
        assert event.source == "broker"

    def test_event_id_auto_generated(self) -> None:
        e1 = OrderEvent(
            order_id="o1",
            event_type=EventType.NEW,
            occurred_at=datetime.now(timezone.utc),
        )
        e2 = OrderEvent(
            order_id="o1",
            event_type=EventType.NEW,
            occurred_at=datetime.now(timezone.utc),
        )
        assert e1.event_id != e2.event_id
