"""HITL (Human-in-the-Loop) queue API routes.

Endpoints:
- GET  /hitl/items              — list pending items
- POST /hitl/items/{id}/claim   — claim an item for review
- POST /hitl/items/{id}/approve — approve a claimed item
- POST /hitl/items/{id}/reject  — reject a claimed item
- POST /hitl/items/{id}/edit    — edit and approve a claimed item

All endpoints require authentication. Approve/reject/edit require analyst+ role.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from astraeus_agent_runtime.hitl import HITLQueue
from astraeus_auth import Principal
from astraeus_auth.dependencies import get_current_user, require_role
from astraeus_auth.models import Role
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/hitl", tags=["hitl"])

# Shared queue instance (in production, backed by Postgres)
_queue = HITLQueue()


def get_hitl_queue() -> HITLQueue:
    """Get the shared HITL queue instance."""
    return _queue


# --- Response schemas ---


class HITLItemResponse(BaseModel):
    id: str
    run_id: str | None = None
    workflow_key: str
    triggered_by: str
    reason: dict[str, Any]
    priority: int
    status: str
    created_at: str
    expires_at: str | None = None


class ClaimRequest(BaseModel):
    claimed_by: str = Field(..., description="UUID of the reviewer claiming this item")


class EditRequest(BaseModel):
    edited_output: dict[str, Any] = Field(
        ..., description="Human-edited output to replace candidate"
    )


class ActionResponse(BaseModel):
    id: str
    status: str
    message: str


# --- Endpoints ---


@router.get("/items", response_model=list[HITLItemResponse], summary="List pending HITL items")
async def list_items(
    user: Annotated[Principal, Depends(get_current_user)],
    status: str = Query(default="pending", description="Filter by status"),
    workflow: str | None = Query(default=None, description="Filter by workflow"),
) -> list[HITLItemResponse]:
    """List HITL queue items, filtered by status."""
    queue = get_hitl_queue()

    if status == "pending":
        items = queue.list_pending(workflow_key=workflow)
    else:
        # Return all items matching status
        items = [item for item in queue._items.values() if item.status.value == status]

    return [
        HITLItemResponse(
            id=str(item.id),
            run_id=str(item.run_id) if item.run_id else None,
            workflow_key=item.workflow_key,
            triggered_by=item.triggered_by,
            reason=item.reason,
            priority=item.priority,
            status=item.status.value,
            created_at=item.created_at.isoformat(),
            expires_at=item.expires_at.isoformat() if item.expires_at else None,
        )
        for item in items
    ]


@router.post("/items/{item_id}/claim", response_model=ActionResponse, summary="Claim an item")
async def claim_item(
    item_id: str,
    request: ClaimRequest,
    user: Annotated[Principal, Depends(require_role(Role.ANALYST, Role.OPERATOR))],
) -> ActionResponse:
    """Claim a pending HITL item for review."""
    queue = get_hitl_queue()

    try:
        iid = uuid.UUID(item_id)
        reviewer_id = uuid.UUID(request.claimed_by)
    except ValueError as err:
        raise HTTPException(status_code=400, detail="Invalid UUID format") from err

    success = queue.claim(iid, reviewer_id)
    if not success:
        raise HTTPException(status_code=409, detail="Item not available for claiming (not pending)")

    return ActionResponse(id=item_id, status="claimed", message="Item claimed for review")


@router.post("/items/{item_id}/approve", response_model=ActionResponse, summary="Approve an item")
async def approve_item(
    item_id: str,
    user: Annotated[Principal, Depends(require_role(Role.ANALYST, Role.OPERATOR))],
) -> ActionResponse:
    """Approve a claimed HITL item — orchestrator resumes from checkpoint."""
    queue = get_hitl_queue()

    try:
        iid = uuid.UUID(item_id)
    except ValueError as err:
        raise HTTPException(status_code=400, detail="Invalid UUID format") from err

    success = queue.approve(iid)
    if not success:
        raise HTTPException(status_code=409, detail="Item not available for approval (not claimed)")

    return ActionResponse(id=item_id, status="approved", message="Item approved, run will resume")


@router.post("/items/{item_id}/reject", response_model=ActionResponse, summary="Reject an item")
async def reject_item(
    item_id: str,
    user: Annotated[Principal, Depends(require_role(Role.ANALYST, Role.OPERATOR))],
    reason: str = Query(default="", description="Rejection reason"),
) -> ActionResponse:
    """Reject a claimed HITL item — run terminates."""
    queue = get_hitl_queue()

    try:
        iid = uuid.UUID(item_id)
    except ValueError as err:
        raise HTTPException(status_code=400, detail="Invalid UUID format") from err

    success = queue.reject(iid, reason=reason)
    if not success:
        raise HTTPException(
            status_code=409, detail="Item not available for rejection (not claimed)"
        )

    return ActionResponse(id=item_id, status="rejected", message="Item rejected, run terminated")


@router.post("/items/{item_id}/edit", response_model=ActionResponse, summary="Edit and approve")
async def edit_item(
    item_id: str,
    request: EditRequest,
    user: Annotated[Principal, Depends(require_role(Role.ANALYST, Role.OPERATOR))],
) -> ActionResponse:
    """Edit a claimed HITL item — orchestrator resumes with human-edited output."""
    queue = get_hitl_queue()

    try:
        iid = uuid.UUID(item_id)
    except ValueError as err:
        raise HTTPException(status_code=400, detail="Invalid UUID format") from err

    success = queue.edit(iid, request.edited_output)
    if not success:
        raise HTTPException(status_code=409, detail="Item not available for editing (not claimed)")

    return ActionResponse(
        id=item_id, status="edited", message="Item edited, run will resume with changes"
    )
