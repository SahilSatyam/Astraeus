"""Unit tests for the OMS service layer.

Tests the order lifecycle: submission, idempotency, cancellation, fills,
and kill switch enforcement.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from astraeus_oms.schemas import SubmitOrderRequest
from astraeus_oms.service import KillSwitchActive, OMSService, OrderAlreadyExists
from astraeus_trading.statemachine import OrderState


@pytest.fixture
def mock_session():
    """Create a mock async session with common query patterns."""
    session = AsyncMock()
    # Default: no kill switches armed, no existing orders
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    session.execute.return_value = mock_result
    return session


@pytest.fixture
def oms_service(mock_session, mock_broker):
    return OMSService(session=mock_session, broker=mock_broker)


@pytest.fixture
def order_request() -> SubmitOrderRequest:
    return SubmitOrderRequest(
        client_order_id="test-001",
        account_id="acct-1",
        strategy_id="momentum_xs",
        symbol="AAPL",
        side="buy",
        qty=Decimal("100"),
        order_type="market",
        tif="DAY",
    )


class TestSubmitOrder:
    """Test order submission flow."""

    @pytest.mark.unit
    async def test_submit_order_success(self, oms_service, order_request, mock_session):
        """Successful order submission transitions through NEW → PENDING_NEW → SUBMITTED."""
        result = await oms_service.submit_order(order_request)

        assert result.order_id is not None
        assert result.client_order_id == "test-001"
        assert result.symbol == "AAPL"
        assert result.side == "buy"
        assert result.state == OrderState.SUBMITTED
        assert result.broker_order_id == "BROKER-test-001"
        assert result.submitted_to == "mock-broker"

    @pytest.mark.unit
    async def test_submit_order_records_events(self, oms_service, order_request, mock_session):
        """Order submission records NEW, PENDING_NEW, and SUBMITTED events."""
        await oms_service.submit_order(order_request)

        # session.add is called for: order, NEW event, PENDING_NEW event, SUBMITTED event, journal
        add_calls = mock_session.add.call_args_list
        assert len(add_calls) >= 4  # order + 3 events + journal

    @pytest.mark.unit
    async def test_submit_order_broker_rejection(self, oms_service, order_request, mock_broker):
        """When broker rejects, order transitions to REJECTED state."""
        mock_broker.set_reject("insufficient buying power")

        result = await oms_service.submit_order(order_request)

        assert result.state == OrderState.REJECTED
        assert result.broker_order_id is None

    @pytest.mark.unit
    async def test_submit_limit_order(self, oms_service, mock_session):
        """Limit orders include limit_price in broker submission."""
        request = SubmitOrderRequest(
            client_order_id="limit-001",
            account_id="acct-1",
            strategy_id="mean_revert",
            symbol="MSFT",
            side="sell",
            qty=Decimal("50"),
            order_type="limit",
            limit_price=Decimal("425.50"),
            tif="GTC",
        )

        result = await oms_service.submit_order(request)

        assert result.state == OrderState.SUBMITTED
        assert result.limit_price == Decimal("425.50")
        assert result.order_type == "limit"


class TestIdempotency:
    """Test idempotent order submission."""

    @pytest.mark.unit
    async def test_duplicate_client_order_id_raises(self, mock_session, mock_broker):
        """Submitting the same client_order_id twice raises OrderAlreadyExists."""
        from astraeus_trading.models import OrderModel

        # First call: no kill switch. Second call: return existing order
        existing_order = MagicMock(spec=OrderModel)
        existing_order.order_id = "existing-id"
        existing_order.client_order_id = "test-001"
        existing_order.account_id = "acct-1"
        existing_order.strategy_id = "momentum_xs"
        existing_order.symbol = "AAPL"
        existing_order.side = "buy"
        existing_order.qty = Decimal("100")
        existing_order.order_type = "market"
        existing_order.limit_price = None
        existing_order.tif = "DAY"
        existing_order.state = OrderState.SUBMITTED
        existing_order.submitted_to = "mock-broker"
        existing_order.broker_order_id = "BROKER-test-001"
        existing_order.created_at = datetime.now(UTC)
        existing_order.updated_at = datetime.now(UTC)

        # First execute: kill switch check (none armed)
        # Second execute: find existing order
        kill_switch_result = MagicMock()
        kill_switch_result.scalars.return_value.first.return_value = None

        existing_result = MagicMock()
        existing_result.scalars.return_value.first.return_value = existing_order

        mock_session.execute.side_effect = [kill_switch_result, existing_result]

        svc = OMSService(session=mock_session, broker=mock_broker)
        request = SubmitOrderRequest(
            client_order_id="test-001",
            account_id="acct-1",
            strategy_id="momentum_xs",
            symbol="AAPL",
            side="buy",
            qty=Decimal("100"),
            order_type="market",
            tif="DAY",
        )

        with pytest.raises(OrderAlreadyExists) as exc_info:
            await svc.submit_order(request)

        assert exc_info.value.existing_order.client_order_id == "test-001"


class TestKillSwitch:
    """Test kill switch enforcement."""

    @pytest.mark.unit
    async def test_global_kill_switch_blocks_order(self, mock_session, mock_broker):
        """Armed global kill switch prevents order submission."""
        from astraeus_trading.models import KillSwitchStateModel

        armed_switch = MagicMock(spec=KillSwitchStateModel)
        armed_switch.scope = "global"
        armed_switch.reason = "maintenance window"

        kill_switch_result = MagicMock()
        kill_switch_result.scalars.return_value.first.return_value = armed_switch
        mock_session.execute.return_value = kill_switch_result

        svc = OMSService(session=mock_session, broker=mock_broker)
        request = SubmitOrderRequest(
            client_order_id="blocked-001",
            account_id="acct-1",
            strategy_id="momentum_xs",
            symbol="AAPL",
            side="buy",
            qty=Decimal("100"),
            order_type="market",
            tif="DAY",
        )

        with pytest.raises(KillSwitchActive) as exc_info:
            await svc.submit_order(request)

        assert exc_info.value.scope == "global"
        assert "maintenance" in exc_info.value.reason

    @pytest.mark.unit
    async def test_account_kill_switch_blocks_order(self, mock_session, mock_broker):
        """Armed account-level kill switch prevents order submission."""
        from astraeus_trading.models import KillSwitchStateModel

        armed_switch = MagicMock(spec=KillSwitchStateModel)
        armed_switch.scope = "account:acct-1"
        armed_switch.reason = "drawdown limit"

        kill_switch_result = MagicMock()
        kill_switch_result.scalars.return_value.first.return_value = armed_switch
        mock_session.execute.return_value = kill_switch_result

        svc = OMSService(session=mock_session, broker=mock_broker)
        request = SubmitOrderRequest(
            client_order_id="blocked-002",
            account_id="acct-1",
            strategy_id="momentum_xs",
            symbol="AAPL",
            side="buy",
            qty=Decimal("100"),
            order_type="market",
            tif="DAY",
        )

        with pytest.raises(KillSwitchActive) as exc_info:
            await svc.submit_order(request)

        assert "account:acct-1" in exc_info.value.scope


class TestCancelOrder:
    """Test order cancellation."""

    @pytest.mark.unit
    async def test_cancel_submitted_order(self, mock_session, mock_broker):
        """Cancelling a submitted order transitions to CANCELLED."""
        from astraeus_brokers.base import BrokerOrderStatus
        from astraeus_trading.models import OrderModel

        # Pre-populate the mock broker with the order
        mock_broker._orders["BROKER-test-001"] = BrokerOrderStatus(
            client_order_id="test-001",
            broker_order_id="BROKER-test-001",
            state="accepted",
        )

        order = MagicMock(spec=OrderModel)
        order.order_id = "order-123"
        order.client_order_id = "test-001"
        order.account_id = "acct-1"
        order.strategy_id = "momentum_xs"
        order.symbol = "AAPL"
        order.side = "buy"
        order.qty = Decimal("100")
        order.order_type = "market"
        order.limit_price = None
        order.tif = "DAY"
        order.state = OrderState.SUBMITTED
        order.submitted_to = "mock-broker"
        order.broker_order_id = "BROKER-test-001"
        order.created_at = datetime.now(UTC)
        order.updated_at = datetime.now(UTC)

        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = order
        mock_session.execute.return_value = result_mock

        svc = OMSService(session=mock_session, broker=mock_broker)
        result = await svc.cancel_order("order-123", reason="user requested")

        assert result.state == OrderState.CANCELLED

    @pytest.mark.unit
    async def test_cancel_filled_order_raises(self, mock_session, mock_broker):
        """Cannot cancel an already-filled order."""
        from astraeus_trading.models import OrderModel

        order = MagicMock(spec=OrderModel)
        order.order_id = "order-456"
        order.state = OrderState.FILLED

        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = order
        mock_session.execute.return_value = result_mock

        svc = OMSService(session=mock_session, broker=mock_broker)

        with pytest.raises(ValueError, match="Cannot cancel"):
            await svc.cancel_order("order-456")


class TestApplyFill:
    """Test fill application."""

    @pytest.mark.unit
    async def test_partial_fill(self, mock_session, mock_broker):
        """Partial fill transitions to PARTIAL_FILL state."""
        from astraeus_trading.models import OrderModel

        order = MagicMock(spec=OrderModel)
        order.order_id = "order-789"
        order.client_order_id = "test-001"
        order.account_id = "acct-1"
        order.strategy_id = "momentum_xs"
        order.symbol = "AAPL"
        order.side = "buy"
        order.qty = Decimal("100")
        order.order_type = "market"
        order.limit_price = None
        order.tif = "DAY"
        order.state = OrderState.SUBMITTED
        order.submitted_to = "mock-broker"
        order.broker_order_id = "BROKER-test-001"
        order.created_at = datetime.now(UTC)
        order.updated_at = datetime.now(UTC)

        # First call: get order. Second call: sum of fills (0 so far)
        order_result = MagicMock()
        order_result.scalars.return_value.first.return_value = order

        sum_result = MagicMock()
        sum_result.scalar_one.return_value = Decimal("0")

        mock_session.execute.side_effect = [order_result, sum_result]

        svc = OMSService(session=mock_session, broker=mock_broker)
        result = await svc.apply_fill(
            order_id="order-789",
            qty=Decimal("50"),
            price=Decimal("175.25"),
            fees=Decimal("0.50"),
        )

        assert result.state == OrderState.PARTIAL_FILL

    @pytest.mark.unit
    async def test_full_fill(self, mock_session, mock_broker):
        """Full fill transitions to FILLED state."""
        from astraeus_trading.models import OrderModel

        order = MagicMock(spec=OrderModel)
        order.order_id = "order-789"
        order.client_order_id = "test-001"
        order.account_id = "acct-1"
        order.strategy_id = "momentum_xs"
        order.symbol = "AAPL"
        order.side = "buy"
        order.qty = Decimal("100")
        order.order_type = "market"
        order.limit_price = None
        order.tif = "DAY"
        order.state = OrderState.PARTIAL_FILL
        order.submitted_to = "mock-broker"
        order.broker_order_id = "BROKER-test-001"
        order.created_at = datetime.now(UTC)
        order.updated_at = datetime.now(UTC)

        order_result = MagicMock()
        order_result.scalars.return_value.first.return_value = order

        # Already filled 50, now filling remaining 50
        sum_result = MagicMock()
        sum_result.scalar_one.return_value = Decimal("50")

        mock_session.execute.side_effect = [order_result, sum_result]

        svc = OMSService(session=mock_session, broker=mock_broker)
        result = await svc.apply_fill(
            order_id="order-789",
            qty=Decimal("50"),
            price=Decimal("175.50"),
        )

        assert result.state == OrderState.FILLED


class TestGetOrder:
    """Test order retrieval."""

    @pytest.mark.unit
    async def test_get_existing_order(self, mock_session, mock_broker):
        """Get order returns the order response."""
        from astraeus_trading.models import OrderModel

        order = MagicMock(spec=OrderModel)
        order.order_id = "order-123"
        order.client_order_id = "test-001"
        order.account_id = "acct-1"
        order.strategy_id = "momentum_xs"
        order.symbol = "AAPL"
        order.side = "buy"
        order.qty = Decimal("100")
        order.order_type = "market"
        order.limit_price = None
        order.tif = "DAY"
        order.state = OrderState.SUBMITTED
        order.submitted_to = "mock-broker"
        order.broker_order_id = "BROKER-test-001"
        order.created_at = datetime.now(UTC)
        order.updated_at = datetime.now(UTC)

        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = order
        mock_session.execute.return_value = result_mock

        svc = OMSService(session=mock_session, broker=mock_broker)
        result = await svc.get_order("order-123")

        assert result.order_id == "order-123"
        assert result.symbol == "AAPL"

    @pytest.mark.unit
    async def test_get_nonexistent_order_raises(self, mock_session, mock_broker):
        """Getting a non-existent order raises ValueError."""
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = result_mock

        svc = OMSService(session=mock_session, broker=mock_broker)

        with pytest.raises(ValueError, match="Order not found"):
            await svc.get_order("nonexistent-id")
