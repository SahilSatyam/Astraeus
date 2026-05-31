"""Unit tests for OMS request/response schemas.

Validates Pydantic model constraints and serialization.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from astraeus_oms.schemas import CancelOrderRequest, OrderResponse, SubmitOrderRequest


class TestSubmitOrderRequest:
    """Test SubmitOrderRequest validation."""

    @pytest.mark.unit
    def test_valid_market_order(self):
        req = SubmitOrderRequest(
            client_order_id="test-001",
            account_id="acct-1",
            strategy_id="momentum_xs",
            symbol="AAPL",
            side="buy",
            qty=Decimal("100"),
            order_type="market",
            tif="DAY",
        )
        assert req.side == "buy"
        assert req.order_type == "market"
        assert req.limit_price is None

    @pytest.mark.unit
    def test_valid_limit_order(self):
        req = SubmitOrderRequest(
            client_order_id="test-002",
            account_id="acct-1",
            strategy_id="mean_revert",
            symbol="MSFT",
            side="sell",
            qty=Decimal("50"),
            order_type="limit",
            limit_price=Decimal("425.50"),
            tif="GTC",
        )
        assert req.limit_price == Decimal("425.50")
        assert req.tif == "GTC"

    @pytest.mark.unit
    def test_invalid_side_rejected(self):
        with pytest.raises(ValueError):
            SubmitOrderRequest(
                client_order_id="test-003",
                account_id="acct-1",
                strategy_id="momentum_xs",
                symbol="AAPL",
                side="short",  # invalid
                qty=Decimal("100"),
            )

    @pytest.mark.unit
    def test_invalid_order_type_rejected(self):
        with pytest.raises(ValueError):
            SubmitOrderRequest(
                client_order_id="test-004",
                account_id="acct-1",
                strategy_id="momentum_xs",
                symbol="AAPL",
                side="buy",
                qty=Decimal("100"),
                order_type="stop_loss",  # invalid
            )

    @pytest.mark.unit
    def test_invalid_tif_rejected(self):
        with pytest.raises(ValueError):
            SubmitOrderRequest(
                client_order_id="test-005",
                account_id="acct-1",
                strategy_id="momentum_xs",
                symbol="AAPL",
                side="buy",
                qty=Decimal("100"),
                tif="IOC",  # invalid
            )

    @pytest.mark.unit
    def test_optional_fields_default_none(self):
        req = SubmitOrderRequest(
            client_order_id="test-006",
            account_id="acct-1",
            strategy_id="momentum_xs",
            symbol="AAPL",
            side="buy",
            qty=Decimal("100"),
        )
        assert req.rec_id is None
        assert req.decision_id is None
        assert req.limit_price is None
        assert req.order_type == "market"
        assert req.tif == "DAY"


class TestCancelOrderRequest:
    """Test CancelOrderRequest validation."""

    @pytest.mark.unit
    def test_empty_reason_allowed(self):
        req = CancelOrderRequest()
        assert req.reason == ""

    @pytest.mark.unit
    def test_reason_preserved(self):
        req = CancelOrderRequest(reason="user requested cancellation")
        assert req.reason == "user requested cancellation"


class TestOrderResponse:
    """Test OrderResponse serialization."""

    @pytest.mark.unit
    def test_decimal_serialization(self):
        from datetime import UTC, datetime

        resp = OrderResponse(
            order_id="order-123",
            client_order_id="test-001",
            account_id="acct-1",
            strategy_id="momentum_xs",
            symbol="AAPL",
            side="buy",
            qty=Decimal("100.5"),
            order_type="market",
            tif="DAY",
            state="submitted",
            submitted_to="alpaca-paper",
            created_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            updated_at=datetime(2026, 1, 15, 10, 0, 1, tzinfo=UTC),
        )
        data = resp.model_dump()
        assert data["qty"] == Decimal("100.5")
        assert data["limit_price"] is None
        assert data["broker_order_id"] is None
