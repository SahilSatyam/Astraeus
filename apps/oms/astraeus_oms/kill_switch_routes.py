"""Kill switch API routes.

Endpoints:
    POST /killswitch/{scope}/arm    — Arm a kill switch
    POST /killswitch/{scope}/disarm — Disarm a kill switch
    GET  /killswitch                — List all kill switch states
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from astraeus_trading.models import KillSwitchStateModel, TradeJournalModel

from astraeus_oms.dependencies import get_session

router = APIRouter(prefix="/killswitch", tags=["kill-switch"])


class ArmRequest(BaseModel):
    armed_by: str = "system"
    reason: str = ""


class KillSwitchResponse(BaseModel):
    scope: str
    armed: bool
    armed_by: str | None = None
    armed_at: datetime | None = None
    reason: str | None = None


@router.post("/{scope}/arm", response_model=KillSwitchResponse)
async def arm_kill_switch(
    scope: str,
    body: ArmRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> KillSwitchResponse:
    """Arm a kill switch for the given scope."""
    now = datetime.now(timezone.utc)

    # Upsert kill switch state
    stmt = select(KillSwitchStateModel).where(KillSwitchStateModel.scope == scope)
    result = await session.execute(stmt)
    ks = result.scalars().first()

    if ks:
        ks.armed = True
        ks.armed_by = body.armed_by
        ks.armed_at = now
        ks.reason = body.reason
    else:
        ks = KillSwitchStateModel(
            scope=scope,
            armed=True,
            armed_by=body.armed_by,
            armed_at=now,
            reason=body.reason,
        )
        session.add(ks)

    # Journal the flip
    journal = TradeJournalModel(
        account_id=scope,
        kind="kill_switch_flip",
        payload={
            "scope": scope,
            "action": "arm",
            "armed_by": body.armed_by,
            "reason": body.reason,
        },
    )
    session.add(journal)
    await session.flush()

    return KillSwitchResponse(
        scope=ks.scope,
        armed=ks.armed,
        armed_by=ks.armed_by,
        armed_at=ks.armed_at,
        reason=ks.reason,
    )


@router.post("/{scope}/disarm", response_model=KillSwitchResponse)
async def disarm_kill_switch(
    scope: str,
    body: ArmRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> KillSwitchResponse:
    """Disarm a kill switch for the given scope."""
    stmt = select(KillSwitchStateModel).where(KillSwitchStateModel.scope == scope)
    result = await session.execute(stmt)
    ks = result.scalars().first()

    if not ks:
        raise HTTPException(status_code=404, detail=f"Kill switch not found: {scope}")

    ks.armed = False

    # Journal the flip
    journal = TradeJournalModel(
        account_id=scope,
        kind="kill_switch_flip",
        payload={
            "scope": scope,
            "action": "disarm",
            "disarmed_by": body.armed_by,
            "reason": body.reason,
        },
    )
    session.add(journal)
    await session.flush()

    return KillSwitchResponse(
        scope=ks.scope,
        armed=ks.armed,
        armed_by=ks.armed_by,
        armed_at=ks.armed_at,
        reason=ks.reason,
    )


@router.get("", response_model=list[KillSwitchResponse])
async def list_kill_switches(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[KillSwitchResponse]:
    """List all kill switch states."""
    stmt = select(KillSwitchStateModel)
    result = await session.execute(stmt)
    switches = result.scalars().all()
    return [
        KillSwitchResponse(
            scope=ks.scope,
            armed=ks.armed,
            armed_by=ks.armed_by,
            armed_at=ks.armed_at,
            reason=ks.reason,
        )
        for ks in switches
    ]
