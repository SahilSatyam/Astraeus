"""Agent runtime API routes.

Endpoints:
- POST /agents/runs              — start a workflow run
- GET  /agents/runs/{run_id}     — get run status and output
- GET  /agents/runs/{run_id}/trace — get run trace (steps + calls)
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from astraeus_api.deps import get_db_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/agents", tags=["agents"])


# --- Request/Response schemas ---


class RunOptions(BaseModel):
    channel: str = Field(default="promoted", description="Prompt registry channel")
    max_cost_usd: float = Field(default=0.50, description="Max cost budget for the run")
    timeout_s: int = Field(default=60, description="Timeout in seconds")


class StartRunRequest(BaseModel):
    workflow: str = Field(
        ...,
        description="Workflow key: trade_thesis, daily_brief, portfolio_commentary, risk_drilldown",
    )
    inputs: dict[str, Any] = Field(default_factory=dict, description="Workflow-specific inputs")
    options: RunOptions = Field(default_factory=RunOptions)


class StartRunResponse(BaseModel):
    run_id: str
    status_url: str


class RunStatus(BaseModel):
    run_id: str
    status: str  # running | completed | hitl_pending | rejected | failed
    workflow_key: str
    output: dict[str, Any] | None = None
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    hitl_required: bool = False
    error: str = ""


class StepTrace(BaseModel):
    step_id: str
    agent_name: str
    status: str
    duration_ms: float = 0.0


class RunTrace(BaseModel):
    run_id: str
    workflow_key: str
    steps: list[StepTrace] = Field(default_factory=list)
    total_cost_usd: float = 0.0
    total_duration_ms: float = 0.0


# --- Endpoints ---


@router.post("/runs", response_model=StartRunResponse, status_code=202, summary="Start a workflow run")
async def start_run(
    request: StartRunRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StartRunResponse:
    """Start an agent workflow run.

    Returns immediately with a run_id. Poll the status URL for results.
    In production, this enqueues the run for async execution.
    """
    from astraeus_agent_runtime.orchestrator import WorkflowOrchestrator

    # Validate workflow
    valid_workflows = {"trade_thesis", "daily_brief", "portfolio_commentary", "risk_drilldown"}
    if request.workflow not in valid_workflows:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid workflow: {request.workflow}. Must be one of: {sorted(valid_workflows)}",
        )

    # For MVP, execute synchronously (production would use task queue)
    orchestrator = WorkflowOrchestrator()
    result = await orchestrator.run_workflow(
        workflow=request.workflow,
        inputs=request.inputs,
        options=request.options.model_dump(),
    )

    run_id = result["run_id"]
    return StartRunResponse(
        run_id=run_id,
        status_url=f"/agents/runs/{run_id}",
    )


@router.get("/runs/{run_id}", response_model=RunStatus, summary="Get run status")
async def get_run_status(
    run_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RunStatus:
    """Get the status and output of a workflow run."""
    try:
        uuid.UUID(run_id)
    except ValueError as err:
        raise HTTPException(status_code=400, detail="Invalid run_id format") from err

    from astraeus_agent_runtime.persistence import load_run

    run = await load_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return RunStatus(
        run_id=run["run_id"],
        status=run["status"],
        workflow_key=run["workflow_key"],
        output=run.get("output"),
        cost_usd=run.get("cost_usd", 0.0),
        duration_ms=run.get("duration_ms", 0.0),
        hitl_required=False,
        error="",
    )


@router.get("/runs/{run_id}/trace", response_model=RunTrace, summary="Get run trace")
async def get_run_trace(
    run_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RunTrace:
    """Get the detailed trace of a workflow run (steps + calls)."""
    try:
        uuid.UUID(run_id)
    except ValueError as err:
        raise HTTPException(status_code=400, detail="Invalid run_id format") from err

    from astraeus_agent_runtime.persistence import load_run, load_run_steps

    run = await load_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    steps = await load_run_steps(session, run_id)

    return RunTrace(
        run_id=run_id,
        workflow_key=run["workflow_key"],
        steps=[
            StepTrace(
                step_id=s["step_id"],
                agent_name=s["agent_name"],
                status=s["status"],
                duration_ms=s.get("duration_ms", 0.0),
            )
            for s in steps
        ],
        total_cost_usd=run.get("cost_usd", 0.0),
        total_duration_ms=run.get("duration_ms", 0.0),
    )
