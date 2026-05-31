"""Position API routes.

Endpoints:
    GET /position/{account_id}          — All positions for an account
    GET /position/{account_id}/{symbol}  — Position for a specific symbol
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from astraeus_trading.models import PositionModel

from astraeus_oms.dependencies import get_session

router = APIRouter(prefix="/position", tags=["positions"])


class PositionResponse(BaseModel):
    account_id: str
    symbol: str
    qty: Decimal
    avg_cost: Decimal
    updated_at: datetime | None = None


@router.get("/{account_id}", response_model=list[PositionResponse])
async def get_positions(
    account_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[PositionResponse]:
    """Get all positions for an account."""
    stmt = select(PositionModel).where(PositionModel.account_id == account_id)
    result = await session.execute(stmt)
    positions = result.scalars().all()
    return [
        PositionResponse(
            account_id=p.account_id,
            symbol=p.symbol,
            qty=Decimal(str(p.qty)),
            avg_cost=Decimal(str(p.avg_cost)),
            updated_at=p.updated_at,
        )
        for p in positions
    ]


@router.get("/{account_id}/{symbol}", response_model=PositionResponse)
async def get_position(
    account_id: str,
    symbol: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PositionResponse:
    """Get position for a specific symbol."""
    stmt = select(PositionModel).where(
        PositionModel.account_id == account_id,
        PositionModel.symbol == symbol,
    )
    result = await session.execute(stmt)
    position = result.scalars().first()
    if not position:
        raise HTTPException(
            status_code=404,
            detail=f"No position found for {account_id}/{symbol}",
        )
    return PositionResponse(
        account_id=position.account_id,
        symbol=position.symbol,
        qty=Decimal(str(position.qty)),
        avg_cost=Decimal(str(position.avg_cost)),
        updated_at=position.updated_at,
    )
