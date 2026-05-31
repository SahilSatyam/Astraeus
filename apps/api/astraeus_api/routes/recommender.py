"""Recommendation engine API routes.

Endpoints:
- GET  /reco/runs?date=YYYY-MM-DD         — list runs for a date
- GET  /reco/run/{run_id}                  — run status and stage timings
- GET  /reco/recommendations?run_id=...    — filtered recommendation list
- POST /reco/recommendations/{rec_id}/decide — approve/reject/override
- GET  /reco/regime?date=YYYY-MM-DD        — regime state for a date
- POST /reco/replay?date=YYYY-MM-DD        — trigger replay for a date
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from astraeus_api.deps import get_db_session

router = APIRouter(prefix="/reco", tags=["recommender"])


# --- Request/Response schemas ---


class RunSummary(BaseModel):
    run_id: str
    run_date: str
    status: str
    started_at: str
    finished_at: str | None = None
    n_recommendations: int = 0


class RunDetail(BaseModel):
    run_id: str
    run_date: str
    status: str
    started_at: str
    finished_at: str | None = None
    input_snapshot_hash: str = ""
    code_commit: str = ""
    stage_timings: dict[str, float] = Field(default_factory=dict)
    failed_stages: list[str] = Field(default_factory=list)
    notes: str = ""


class RecommendationResponse(BaseModel):
    rec_id: str
    run_id: str
    ticker: str
    side: str
    target_weight: float
    rank: int
    composite_score: float
    component_attribution: dict[str, float]
    risk_passed: bool
    thesis_summary: str = ""
    state: str
    horizon_days: int = 60
    created_at: str


class DecideRequest(BaseModel):
    decision: str = Field(..., description="approve | reject | override")
    override_weight: float | None = Field(default=None, description="New weight if overriding")
    rationale: str = Field(default="", description="Reason for the decision")
    decided_by: str = Field(default="operator")


class DecideResponse(BaseModel):
    rec_id: str
    new_state: str
    decided_at: str


class RegimeResponse(BaseModel):
    run_date: str
    label: str
    probability: float
    stability_days: int = 0
    model: str = "hmm_v1"


class ReplayRequest(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD date to replay")


class ReplayResponse(BaseModel):
    run_id: str
    status: str
    message: str


# --- Endpoints ---


@router.get("/runs", response_model=list[RunSummary], summary="List runs for a date")
async def list_runs(
    date: str = Query(..., description="YYYY-MM-DD"),
    session: Any = Depends(get_db_session),
) -> list[RunSummary]:
    """List all pipeline runs for a given date."""
    from sqlalchemy import text

    result = await session.execute(
        text("""
            SELECT r.run_id, r.run_date, r.status, r.started_at, r.finished_at,
                   (SELECT COUNT(*) FROM recommendation WHERE run_id = r.run_id) as n_recs
            FROM recommender_run r
            WHERE r.run_date = :run_date
            ORDER BY r.started_at DESC
        """),
        {"run_date": date},
    )
    rows = result.all()

    return [
        RunSummary(
            run_id=str(row[0]),
            run_date=str(row[1]),
            status=row[2],
            started_at=row[3].isoformat() if row[3] else "",
            finished_at=row[4].isoformat() if row[4] else None,
            n_recommendations=row[5] or 0,
        )
        for row in rows
    ]


@router.get("/run/{run_id}", response_model=RunDetail, summary="Get run details")
async def get_run(
    run_id: str,
    session: Any = Depends(get_db_session),
) -> RunDetail:
    """Get detailed status and stage timings for a pipeline run."""
    from sqlalchemy import text

    result = await session.execute(
        text("""
            SELECT run_id, run_date, status, started_at, finished_at,
                   input_snapshot_hash, code_commit, notes
            FROM recommender_run
            WHERE run_id = :run_id::uuid
        """),
        {"run_id": run_id},
    )
    row = result.one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return RunDetail(
        run_id=str(row[0]),
        run_date=str(row[1]),
        status=row[2],
        started_at=row[3].isoformat() if row[3] else "",
        finished_at=row[4].isoformat() if row[4] else None,
        input_snapshot_hash=row[5].hex() if row[5] else "",
        code_commit=row[6] or "",
        notes=row[7] or "",
    )


@router.get(
    "/recommendations", response_model=list[RecommendationResponse], summary="List recommendations"
)
async def list_recommendations(
    run_id: str = Query(..., description="Filter by run_id"),
    state: str | None = Query(default=None, description="Filter by state"),
    session: Any = Depends(get_db_session),
) -> list[RecommendationResponse]:
    """List recommendations for a run, optionally filtered by state."""
    from sqlalchemy import text

    query = """
        SELECT rec_id, run_id, ticker, side, target_weight, rank,
               composite_score, component_attribution, risk_passed,
               state, horizon_days, created_at
        FROM recommendation
        WHERE run_id = :run_id::uuid
    """
    params: dict[str, Any] = {"run_id": run_id}

    if state:
        query += " AND state = :state"
        params["state"] = state

    query += " ORDER BY rank ASC"

    result = await session.execute(text(query), params)
    rows = result.all()

    return [
        RecommendationResponse(
            rec_id=str(row[0]),
            run_id=str(row[1]),
            ticker=row[2],
            side=row[3],
            target_weight=row[4],
            rank=row[5],
            composite_score=row[6],
            component_attribution=row[7] or {},
            risk_passed=row[8],
            state=row[9],
            horizon_days=row[10],
            created_at=row[11].isoformat() if row[11] else "",
        )
        for row in rows
    ]


@router.post(
    "/recommendations/{rec_id}/decide",
    response_model=DecideResponse,
    summary="Decide on a recommendation",
)
async def decide_recommendation(
    rec_id: str,
    request: DecideRequest,
    session: Any = Depends(get_db_session),
) -> DecideResponse:
    """Approve, reject, or override a recommendation."""
    from datetime import datetime

    from sqlalchemy import text

    # Validate decision
    valid_decisions = {"approve", "reject", "override"}
    if request.decision not in valid_decisions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid decision: {request.decision}. Must be one of: {sorted(valid_decisions)}",
        )

    if request.decision == "override" and request.override_weight is None:
        raise HTTPException(
            status_code=400, detail="override_weight required for override decision"
        )

    # Check recommendation exists and is in proposed state
    result = await session.execute(
        text("SELECT state FROM recommendation WHERE rec_id = :rec_id::uuid"),
        {"rec_id": rec_id},
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Recommendation {rec_id} not found")
    if row[0] != "proposed":
        raise HTTPException(
            status_code=409, detail=f"Recommendation is in state '{row[0]}', not 'proposed'"
        )

    # Map decision to new state
    state_map = {"approve": "approved", "reject": "rejected", "override": "overridden"}
    new_state = state_map[request.decision]

    now = datetime.now(tz=UTC)

    # Update recommendation state
    await session.execute(
        text("UPDATE recommendation SET state = :state WHERE rec_id = :rec_id::uuid"),
        {"state": new_state, "rec_id": rec_id},
    )

    # Insert decision record
    await session.execute(
        text("""
            INSERT INTO recommendation_decision (rec_id, decided_at, decided_by, decision, override_weight, rationale)
            VALUES (:rec_id::uuid, :decided_at, :decided_by, :decision, :override_weight, :rationale)
        """),
        {
            "rec_id": rec_id,
            "decided_at": now,
            "decided_by": request.decided_by,
            "decision": request.decision,
            "override_weight": request.override_weight,
            "rationale": request.rationale,
        },
    )

    await session.commit()

    return DecideResponse(
        rec_id=rec_id,
        new_state=new_state,
        decided_at=now.isoformat(),
    )


@router.get("/regime", response_model=RegimeResponse | None, summary="Get regime for a date")
async def get_regime(
    date: str = Query(..., description="YYYY-MM-DD"),
    session: Any = Depends(get_db_session),
) -> RegimeResponse | None:
    """Get the detected regime state for a given date."""
    from sqlalchemy import text

    result = await session.execute(
        text("""
            SELECT rs.label, rs.probability, rs.model, r.run_date
            FROM regime_state rs
            JOIN recommender_run r ON r.run_id = rs.run_id
            WHERE r.run_date = :run_date
            ORDER BY rs.detected_at DESC
            LIMIT 1
        """),
        {"run_date": date},
    )
    row = result.one_or_none()

    if row is None:
        return None

    return RegimeResponse(
        run_date=str(row[3]),
        label=row[0],
        probability=row[1],
        model=row[2],
    )


@router.post(
    "/replay", response_model=ReplayResponse, status_code=202, summary="Trigger pipeline replay"
)
async def trigger_replay(
    request: ReplayRequest,
    session: Any = Depends(get_db_session),
) -> ReplayResponse:
    """Trigger a pipeline replay for a historical date.

    This re-runs the pipeline with the same input data to verify determinism.
    In production, this would enqueue a task; for MVP it returns immediately.
    """
    import uuid

    run_id = str(uuid.uuid4())

    return ReplayResponse(
        run_id=run_id,
        status="queued",
        message=f"Replay queued for {request.date}. Run ID: {run_id}",
    )
