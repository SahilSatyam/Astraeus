"""Unit tests for the reconciliation worker.

Tests position reconciliation, order reconciliation, drift detection,
and kill switch arming on drift.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from astraeus_brokers.base import BrokerPosition
from astraeus_recon_worker.worker import ReconciliationWorker


@pytest.fixture
def mock_sessionmaker():
    """Create a mock async sessionmaker."""
    session = AsyncMock()
    sessionmaker = MagicMock()
    sessionmaker.return_value.__aenter__ = AsyncMock(return_value=session)
    sessionmaker.return_value.__aexit__ = AsyncMock(return_value=None)
    return sessionmaker, session


@pytest.fixture
def mock_broker():
    """Create a mock broker adapter."""
    broker = AsyncMock()
    broker.name = "mock-broker"
    broker.get_positions.return_value = []
    broker.get_orders.return_value = []
    return broker


class TestRunOnce:
    """Test single reconciliation cycle."""

    @pytest.mark.unit
    async def test_no_drift_when_positions_match(self, mock_sessionmaker, mock_broker):
        """No drift when broker and local positions match."""
        sessionmaker, session = mock_sessionmaker

        # Broker has AAPL: 100 shares
        mock_broker.get_positions.return_value = [
            BrokerPosition(symbol="AAPL", qty=Decimal("100"), avg_cost=Decimal("150.0"))
        ]

        # Local also has AAPL: 100 shares
        local_pos = MagicMock()
        local_pos.symbol = "AAPL"
        local_pos.qty = Decimal("100")
        local_pos.avg_cost = Decimal("150.0")
        local_pos.account_id = "acct-1"

        pos_result = MagicMock()
        pos_result.scalars.return_value.all.return_value = [local_pos]

        # No open orders
        order_result = MagicMock()
        order_result.scalars.return_value.all.return_value = []

        session.execute.side_effect = [pos_result, order_result]

        worker = ReconciliationWorker(
            sessionmaker=sessionmaker,
            broker=mock_broker,
            account_id="acct-1",
            pause_on_drift=False,
        )
        drift_count = await worker.run_once()
        assert drift_count == 0

    @pytest.mark.unit
    async def test_drift_when_qty_mismatch(self, mock_sessionmaker, mock_broker):
        """Drift detected when position quantities don't match."""
        sessionmaker, session = mock_sessionmaker

        # Broker: 100 shares
        mock_broker.get_positions.return_value = [
            BrokerPosition(symbol="AAPL", qty=Decimal("100"), avg_cost=Decimal("150.0"))
        ]

        # Local: 90 shares (drift!)
        local_pos = MagicMock()
        local_pos.symbol = "AAPL"
        local_pos.qty = Decimal("90")
        local_pos.avg_cost = Decimal("150.0")

        pos_result = MagicMock()
        pos_result.scalars.return_value.all.return_value = [local_pos]

        order_result = MagicMock()
        order_result.scalars.return_value.all.return_value = []

        session.execute.side_effect = [pos_result, order_result]

        worker = ReconciliationWorker(
            sessionmaker=sessionmaker,
            broker=mock_broker,
            account_id="acct-1",
            pause_on_drift=False,
        )
        drift_count = await worker.run_once()
        assert drift_count == 1

    @pytest.mark.unit
    async def test_drift_when_broker_has_unknown_position(self, mock_sessionmaker, mock_broker):
        """Drift detected when broker has a position we don't know about."""
        sessionmaker, session = mock_sessionmaker

        # Broker has TSLA, local has nothing
        mock_broker.get_positions.return_value = [
            BrokerPosition(symbol="TSLA", qty=Decimal("50"), avg_cost=Decimal("200.0"))
        ]

        pos_result = MagicMock()
        pos_result.scalars.return_value.all.return_value = []

        order_result = MagicMock()
        order_result.scalars.return_value.all.return_value = []

        session.execute.side_effect = [pos_result, order_result]

        worker = ReconciliationWorker(
            sessionmaker=sessionmaker,
            broker=mock_broker,
            account_id="acct-1",
            pause_on_drift=False,
        )
        drift_count = await worker.run_once()
        assert drift_count == 1

    @pytest.mark.unit
    async def test_drift_when_local_has_orphan_position(self, mock_sessionmaker, mock_broker):
        """Drift detected when local has a position broker doesn't."""
        sessionmaker, session = mock_sessionmaker

        # Broker has nothing
        mock_broker.get_positions.return_value = []

        # Local has AAPL: 100 shares
        local_pos = MagicMock()
        local_pos.symbol = "AAPL"
        local_pos.qty = Decimal("100")
        local_pos.avg_cost = Decimal("150.0")

        pos_result = MagicMock()
        pos_result.scalars.return_value.all.return_value = [local_pos]

        order_result = MagicMock()
        order_result.scalars.return_value.all.return_value = []

        session.execute.side_effect = [pos_result, order_result]

        worker = ReconciliationWorker(
            sessionmaker=sessionmaker,
            broker=mock_broker,
            account_id="acct-1",
            pause_on_drift=False,
        )
        drift_count = await worker.run_once()
        assert drift_count == 1


class TestPauseOnDrift:
    """Test kill switch arming on drift detection."""

    @pytest.mark.unit
    async def test_arms_kill_switch_on_drift(self, mock_sessionmaker, mock_broker):
        """Kill switch is armed when drift is detected and pause_on_drift=True."""
        sessionmaker, session = mock_sessionmaker

        # Broker has unknown position
        mock_broker.get_positions.return_value = [
            BrokerPosition(symbol="TSLA", qty=Decimal("50"), avg_cost=Decimal("200.0"))
        ]

        pos_result = MagicMock()
        pos_result.scalars.return_value.all.return_value = []

        order_result = MagicMock()
        order_result.scalars.return_value.all.return_value = []

        # Kill switch lookup returns None (not yet armed)
        ks_result = MagicMock()
        ks_result.scalars.return_value.first.return_value = None

        session.execute.side_effect = [pos_result, order_result, ks_result]

        worker = ReconciliationWorker(
            sessionmaker=sessionmaker,
            broker=mock_broker,
            account_id="acct-1",
            pause_on_drift=True,
        )
        drift_count = await worker.run_once()
        assert drift_count == 1
        # Should have added a kill switch model
        session.add.assert_called()


class TestStopSignal:
    """Test worker stop mechanism."""

    @pytest.mark.unit
    def test_stop_sets_running_false(self, mock_sessionmaker, mock_broker):
        """Calling stop() sets _running to False."""
        sessionmaker, _ = mock_sessionmaker
        worker = ReconciliationWorker(
            sessionmaker=sessionmaker,
            broker=mock_broker,
            account_id="acct-1",
        )
        worker._running = True
        worker.stop()
        assert worker._running is False
