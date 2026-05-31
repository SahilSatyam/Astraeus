"""Reconciliation worker.

Runs on a 5-second cadence, comparing local position/order state against the
broker's reported state. Any drift is recorded in ``reconciliation_diff`` and
triggers an alert. If drift > 0, new order submissions are paused.

Flow:
1. Fetch positions from broker.
2. Fetch local positions from DB.
3. Compare; record diffs.
4. Fetch open orders from broker.
5. Compare against local order states.
6. If any drift detected: pause submissions (arm kill switch for account).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from astraeus_brokers.base import BrokerAdapter
from astraeus_trading.models import (
    KillSwitchStateModel,
    OrderModel,
    PositionModel,
    ReconciliationDiffModel,
    TradeJournalModel,
)
from astraeus_trading.statemachine import TERMINAL_STATES
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


class ReconciliationWorker:
    """Reconciliation worker that runs on a configurable cadence."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        broker: BrokerAdapter,
        account_id: str,
        cadence_seconds: float = 5.0,
        pause_on_drift: bool = True,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._broker = broker
        self._account_id = account_id
        self._cadence = cadence_seconds
        self._pause_on_drift = pause_on_drift
        self._running = False

    async def run_once(self) -> int:
        """Run a single reconciliation cycle. Returns number of drifts found."""
        drift_count = 0

        async with self._sessionmaker() as session:
            try:
                # Reconcile positions
                drift_count += await self._reconcile_positions(session)

                # Reconcile open orders
                drift_count += await self._reconcile_orders(session)

                if drift_count > 0 and self._pause_on_drift:
                    await self._pause_submissions(session, drift_count)
                    logger.warning(
                        "Reconciliation drift detected",
                        extra={
                            "drift_count": drift_count,
                            "account_id": self._account_id,
                        },
                    )

                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Reconciliation cycle failed")
                raise

        return drift_count

    async def run_loop(self) -> None:
        """Run the reconciliation loop indefinitely."""
        self._running = True
        logger.info(
            "Reconciliation worker started",
            extra={"cadence_seconds": self._cadence, "account_id": self._account_id},
        )
        while self._running:
            try:
                await self.run_once()
            except Exception:
                logger.exception("Reconciliation cycle error, will retry")
            await asyncio.sleep(self._cadence)

    def stop(self) -> None:
        """Signal the worker to stop."""
        self._running = False

    async def _reconcile_positions(self, session: AsyncSession) -> int:
        """Compare broker positions vs local positions."""
        broker_positions = await self._broker.get_positions()
        broker_map = {p.symbol: p for p in broker_positions}

        # Fetch local positions
        stmt = select(PositionModel).where(PositionModel.account_id == self._account_id)
        result = await session.execute(stmt)
        local_positions = {p.symbol: p for p in result.scalars().all()}

        drift_count = 0

        # Check broker positions against local
        for symbol, bp in broker_map.items():
            lp = local_positions.get(symbol)
            if lp is None:
                # Broker has position we don't know about
                await self._record_drift(
                    session,
                    kind="position",
                    local_repr=None,
                    broker_repr={
                        "symbol": symbol,
                        "qty": str(bp.qty),
                        "avg_cost": str(bp.avg_cost),
                    },
                )
                drift_count += 1
            elif Decimal(str(lp.qty)) != bp.qty:
                await self._record_drift(
                    session,
                    kind="position",
                    local_repr={
                        "symbol": symbol,
                        "qty": str(lp.qty),
                        "avg_cost": str(lp.avg_cost),
                    },
                    broker_repr={
                        "symbol": symbol,
                        "qty": str(bp.qty),
                        "avg_cost": str(bp.avg_cost),
                    },
                )
                drift_count += 1

        # Check local positions not in broker
        for symbol, lp in local_positions.items():
            if symbol not in broker_map and Decimal(str(lp.qty)) != Decimal("0"):
                await self._record_drift(
                    session,
                    kind="position",
                    local_repr={
                        "symbol": symbol,
                        "qty": str(lp.qty),
                        "avg_cost": str(lp.avg_cost),
                    },
                    broker_repr=None,
                )
                drift_count += 1

        return drift_count

    async def _reconcile_orders(self, session: AsyncSession) -> int:
        """Compare broker open orders vs local non-terminal orders."""
        broker_orders = await self._broker.get_orders(status="open")
        broker_ids = {o.broker_order_id for o in broker_orders if o.broker_order_id}

        # Fetch local non-terminal orders
        terminal_states = [s.value for s in TERMINAL_STATES]
        stmt = select(OrderModel).where(
            OrderModel.account_id == self._account_id,
            OrderModel.state.notin_(terminal_states),
        )
        result = await session.execute(stmt)
        local_orders = result.scalars().all()
        local_broker_ids = {o.broker_order_id for o in local_orders if o.broker_order_id}

        drift_count = 0

        # Orders in broker but not local
        for bid in broker_ids - local_broker_ids:
            await self._record_drift(
                session,
                kind="order",
                local_repr=None,
                broker_repr={"broker_order_id": bid, "status": "open"},
            )
            drift_count += 1

        # Orders in local but not broker (might have been filled/cancelled)
        for bid in local_broker_ids - broker_ids:
            order = next((o for o in local_orders if o.broker_order_id == bid), None)
            if order:
                await self._record_drift(
                    session,
                    kind="order",
                    local_repr={
                        "order_id": order.order_id,
                        "broker_order_id": bid,
                        "state": order.state,
                    },
                    broker_repr=None,
                )
                drift_count += 1

        return drift_count

    async def _record_drift(
        self,
        session: AsyncSession,
        kind: str,
        local_repr: dict | None,
        broker_repr: dict | None,
    ) -> None:
        """Record a reconciliation drift."""
        diff = ReconciliationDiffModel(
            diff_id=str(uuid.uuid4()),
            account_id=self._account_id,
            kind=kind,
            local_repr=local_repr,
            broker_repr=broker_repr,
        )
        session.add(diff)

        # Journal the drift
        journal = TradeJournalModel(
            account_id=self._account_id,
            kind="recon_drift",
            payload={
                "kind": kind,
                "local": local_repr,
                "broker": broker_repr,
            },
        )
        session.add(journal)

    async def _pause_submissions(self, session: AsyncSession, drift_count: int) -> None:
        """Arm kill switch for the account to pause new submissions."""
        scope = f"account:{self._account_id}"
        stmt = select(KillSwitchStateModel).where(KillSwitchStateModel.scope == scope)
        result = await session.execute(stmt)
        ks = result.scalars().first()

        now = datetime.now(UTC)
        if ks:
            if not ks.armed:
                ks.armed = True
                ks.armed_by = "recon_worker"
                ks.armed_at = now
                ks.reason = f"Reconciliation drift detected: {drift_count} diffs"
        else:
            ks = KillSwitchStateModel(
                scope=scope,
                armed=True,
                armed_by="recon_worker",
                armed_at=now,
                reason=f"Reconciliation drift detected: {drift_count} diffs",
            )
            session.add(ks)
