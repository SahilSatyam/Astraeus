"""Reconciliation API routes.

Endpoints:
    GET /recon/drift — List unresolved reconciliation drifts
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from astraeus_trading.models import ReconciliationDiffModel
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from astraeus_oms.dependencies import get_session

router = APIRouter(prefix="/recon", tags=["reconciliation"])


class DriftResponse(BaseModel):
    diff_id: str
    account_id: str
    kind: str
    local_repr: dict[str, Any] | None = None
    broker_repr: dict[str, Any] | None = None
    detected_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution: str | None = None


@router.get("/drift", response_model=list[DriftResponse])
async def list_drifts(
    session: Annotated[AsyncSession, Depends(get_session)],
    since: Annotated[datetime | None, Query()] = None,
    resolved: Annotated[bool, Query()] = False,
) -> list[DriftResponse]:
    """List reconciliation drifts."""
    stmt = select(ReconciliationDiffModel)

    if since:
        stmt = stmt.where(ReconciliationDiffModel.detected_at >= since)

    if not resolved:
        stmt = stmt.where(ReconciliationDiffModel.resolved_at.is_(None))

    stmt = stmt.order_by(ReconciliationDiffModel.detected_at.desc()).limit(100)

    result = await session.execute(stmt)
    diffs = result.scalars().all()
    return [
        DriftResponse(
            diff_id=d.diff_id,
            account_id=d.account_id,
            kind=d.kind,
            local_repr=d.local_repr,
            broker_repr=d.broker_repr,
            detected_at=d.detected_at,
            resolved_at=d.resolved_at,
            resolution=d.resolution,
        )
        for d in diffs
    ]
