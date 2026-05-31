"""Position service — maintains position snapshots from fills.

Positions are updated incrementally as fills arrive. The position table
is a materialized view of the fill stream, not a source of truth — the
fills table is the source of truth.

Position = sum of all fills for (account, symbol), with weighted average cost.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from astraeus_trading.models import FillModel, OrderModel, PositionModel


class PositionService:
    """Manages position state derived from fills."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def apply_fill(
        self,
        account_id: str,
        symbol: str,
        side: str,
        fill_qty: Decimal,
        fill_price: Decimal,
    ) -> PositionModel:
        """Update position after a fill.

        For buys: increase qty, update weighted avg cost.
        For sells: decrease qty, avg cost unchanged (realized PnL tracked elsewhere).
        """
        position = await self._get_or_create(account_id, symbol)

        current_qty = Decimal(str(position.qty))
        current_avg = Decimal(str(position.avg_cost))

        if side == "buy":
            new_qty = current_qty + fill_qty
            if new_qty != Decimal("0"):
                # Weighted average cost
                new_avg = (
                    (current_qty * current_avg) + (fill_qty * fill_price)
                ) / new_qty
            else:
                new_avg = Decimal("0")
        else:  # sell
            new_qty = current_qty - fill_qty
            new_avg = current_avg  # avg cost doesn't change on sells

        position.qty = new_qty
        position.avg_cost = new_avg
        await self._session.flush()
        return position

    async def rebuild_from_fills(self, account_id: str) -> list[PositionModel]:
        """Rebuild all positions for an account from the fill history.

        Used for reconciliation or crash recovery.
        """
        # Get all fills for this account via orders
        stmt = (
            select(FillModel, OrderModel)
            .join(OrderModel, FillModel.order_id == OrderModel.order_id)
            .where(OrderModel.account_id == account_id)
            .order_by(FillModel.occurred_at)
        )
        result = await self._session.execute(stmt)
        rows = result.all()

        # Aggregate positions
        positions: dict[str, tuple[Decimal, Decimal]] = {}  # symbol -> (qty, avg_cost)

        for fill, order in rows:
            symbol = order.symbol
            side = order.side
            fill_qty = Decimal(str(fill.qty))
            fill_price = Decimal(str(fill.price))

            current_qty, current_avg = positions.get(symbol, (Decimal("0"), Decimal("0")))

            if side == "buy":
                new_qty = current_qty + fill_qty
                if new_qty != Decimal("0"):
                    new_avg = (
                        (current_qty * current_avg) + (fill_qty * fill_price)
                    ) / new_qty
                else:
                    new_avg = Decimal("0")
            else:
                new_qty = current_qty - fill_qty
                new_avg = current_avg

            positions[symbol] = (new_qty, new_avg)

        # Upsert positions
        updated: list[PositionModel] = []
        for symbol, (qty, avg_cost) in positions.items():
            pos = await self._get_or_create(account_id, symbol)
            pos.qty = qty
            pos.avg_cost = avg_cost
            updated.append(pos)

        await self._session.flush()
        return updated

    async def get_position(self, account_id: str, symbol: str) -> PositionModel | None:
        """Get a single position."""
        stmt = select(PositionModel).where(
            PositionModel.account_id == account_id,
            PositionModel.symbol == symbol,
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_all_positions(self, account_id: str) -> list[PositionModel]:
        """Get all positions for an account."""
        stmt = select(PositionModel).where(PositionModel.account_id == account_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _get_or_create(self, account_id: str, symbol: str) -> PositionModel:
        """Get existing position or create a new zero position."""
        stmt = select(PositionModel).where(
            PositionModel.account_id == account_id,
            PositionModel.symbol == symbol,
        )
        result = await self._session.execute(stmt)
        position = result.scalars().first()

        if position is None:
            position = PositionModel(
                account_id=account_id,
                symbol=symbol,
                qty=Decimal("0"),
                avg_cost=Decimal("0"),
            )
            self._session.add(position)
            await self._session.flush()

        return position
