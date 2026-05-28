"""Market data API routes.

Endpoints:
- POST /md/backfill — trigger a backfill ingestion run
- GET  /md/runs/{run_id} — get ingestion run status
- GET  /md/lineage — query data lineage for a specific row
- GET  /md/gaps — list detected data gaps
- GET  /md/bars — query stored bars
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated

from astraeus_config import Settings
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from astraeus_api.deps import get_db_session, get_settings
from astraeus_marketdata.adapters.yahoo import YahooAdapter
from astraeus_marketdata.ingestion import IngestionRun, run_ingestion
from astraeus_marketdata.models import DataGap, DataLineage, MarketBarRaw

router = APIRouter(prefix="/md", tags=["market-data"])

# --- Request/Response schemas ---


class BackfillRequest(BaseModel):
    source: str = Field(default="yahoo", description="Data source adapter to use")
    symbols: list[str] = Field(..., description="List of ticker symbols", min_length=1)
    start: date = Field(..., description="Start date (inclusive)")
    end: date = Field(..., description="End date (inclusive)")
    resolution: str = Field(default="1d", description="Bar resolution (1d, 1h, 1m)")
    dry_run: bool = Field(default=False, description="If true, fetch but don't persist")


class BackfillResponse(BaseModel):
    run_id: str
    source: str
    status: str
    symbols_count: int
    rows_fetched: int
    rows_written: int
    rows_skipped: int
    started_at: str
    completed_at: str | None


class LineageEntry(BaseModel):
    target_table: str
    target_pk: dict
    source: str
    source_endpoint: str | None
    source_response_hash: str
    schema_version: int
    ingest_run_id: str
    written_at: str


class GapEntry(BaseModel):
    symbol: str
    resolution: str
    expected_ts: str
    detected_at: str
    resolved_at: str | None


class BarEntry(BaseModel):
    symbol: str
    ts: str
    resolution: str
    open: str
    high: str
    low: str
    close: str
    volume: int | None
    vwap: str | None
    source: str


# --- In-memory run tracking (simple for now; Phase 2 moves to DB) ---
_runs: dict[str, IngestionRun] = {}


# --- Endpoints ---


@router.post("/backfill", response_model=BackfillResponse, summary="Trigger a backfill run")
async def backfill(
    request: BackfillRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> BackfillResponse:
    """Start a market data backfill for the given symbols and date range."""
    # Select adapter based on source
    if request.source == "yahoo":
        adapter = YahooAdapter()
    elif request.source == "alpaca":
        from astraeus_marketdata.adapters.alpaca import AlpacaAdapter

        adapter = AlpacaAdapter(
            api_key=settings.alpaca_api_key,
            api_secret=settings.alpaca_api_secret,
        )
    elif request.source == "polygon":
        from astraeus_marketdata.adapters.polygon import PolygonAdapter

        adapter = PolygonAdapter(api_key=settings.polygon_api_key)
    elif request.source == "alphavantage":
        from astraeus_marketdata.adapters.alphavantage import AlphaVantageAdapter

        adapter = AlphaVantageAdapter(api_key=settings.alphavantage_api_key)
    elif request.source == "fred":
        from astraeus_marketdata.adapters.fred import FredAdapter

        adapter = FredAdapter(api_key=settings.fred_api_key)
    else:
        from astraeus_domain import AstraeusError

        raise AstraeusError(
            f"Unsupported source: {request.source}",
            code="astraeus.md.unsupported_source",
            status=400,
        )

    try:
        run = await run_ingestion(
            adapter=adapter,
            session=session,
            symbols=request.symbols,
            start=request.start,
            end=request.end,
            resolution=request.resolution,
        )
        _runs[str(run.run_id)] = run
    finally:
        await adapter.close()

    return BackfillResponse(
        run_id=str(run.run_id),
        source=run.source,
        status=run.status,
        symbols_count=len(run.symbols),
        rows_fetched=run.rows_fetched,
        rows_written=run.rows_written,
        rows_skipped=run.rows_skipped,
        started_at=run.started_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


@router.get("/runs/{run_id}", response_model=BackfillResponse, summary="Get run status")
async def get_run(run_id: str) -> BackfillResponse:
    """Get the status of a previous ingestion run."""
    run = _runs.get(run_id)
    if not run:
        from astraeus_domain import NotFoundError

        raise NotFoundError(f"Run {run_id} not found", code="astraeus.md.run_not_found")

    return BackfillResponse(
        run_id=str(run.run_id),
        source=run.source,
        status=run.status,
        symbols_count=len(run.symbols),
        rows_fetched=run.rows_fetched,
        rows_written=run.rows_written,
        rows_skipped=run.rows_skipped,
        started_at=run.started_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


@router.get("/lineage", response_model=list[LineageEntry], summary="Query data lineage")
async def get_lineage(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    table: str = Query(default="market_bars_raw", description="Target table"),
    symbol: str | None = Query(default=None, description="Filter by symbol"),
    limit: int = Query(default=50, le=500),
) -> list[LineageEntry]:
    """Query lineage records for a specific table and optional symbol filter."""
    query = select(DataLineage).where(DataLineage.target_table == table)

    if symbol:
        query = query.where(DataLineage.target_pk["symbol"].astext == symbol)

    query = query.order_by(DataLineage.written_at.desc()).limit(limit)
    result = await session.execute(query)
    rows = result.scalars().all()

    return [
        LineageEntry(
            target_table=row.target_table,
            target_pk=row.target_pk,
            source=row.source,
            source_endpoint=row.source_endpoint,
            source_response_hash=row.source_response_hash.hex(),
            schema_version=row.schema_version,
            ingest_run_id=str(row.ingest_run_id),
            written_at=row.written_at.isoformat(),
        )
        for row in rows
    ]


@router.get("/gaps", response_model=list[GapEntry], summary="List data gaps")
async def get_gaps(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    symbol: str | None = Query(default=None),
    resolved: bool = Query(default=False, description="Include resolved gaps"),
    limit: int = Query(default=100, le=1000),
) -> list[GapEntry]:
    """List detected data gaps, optionally filtered by symbol."""
    query = select(DataGap)

    if symbol:
        query = query.where(DataGap.symbol == symbol)
    if not resolved:
        query = query.where(DataGap.resolved_at.is_(None))

    query = query.order_by(DataGap.detected_at.desc()).limit(limit)
    result = await session.execute(query)
    rows = result.scalars().all()

    return [
        GapEntry(
            symbol=row.symbol,
            resolution=row.resolution,
            expected_ts=row.expected_ts.isoformat(),
            detected_at=row.detected_at.isoformat(),
            resolved_at=row.resolved_at.isoformat() if row.resolved_at else None,
        )
        for row in rows
    ]


@router.get("/bars", response_model=list[BarEntry], summary="Query stored bars")
async def get_bars(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    symbol: str = Query(..., description="Ticker symbol"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    resolution: str = Query(default="1d"),
    source: str | None = Query(default=None),
    limit: int = Query(default=100, le=10000),
) -> list[BarEntry]:
    """Query raw market bars from the database."""
    query = select(MarketBarRaw).where(
        MarketBarRaw.symbol == symbol,
        MarketBarRaw.resolution == resolution,
    )

    if start:
        query = query.where(
            MarketBarRaw.ts >= datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
        )
    if end:
        query = query.where(
            MarketBarRaw.ts
            <= datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc)
        )
    if source:
        query = query.where(MarketBarRaw.source == source)

    query = query.order_by(MarketBarRaw.ts).limit(limit)
    result = await session.execute(query)
    rows = result.scalars().all()

    return [
        BarEntry(
            symbol=row.symbol,
            ts=row.ts.isoformat(),
            resolution=row.resolution,
            open=str(row.open),
            high=str(row.high),
            low=str(row.low),
            close=str(row.close),
            volume=row.volume,
            vwap=str(row.vwap) if row.vwap else None,
            source=row.source,
        )
        for row in rows
    ]


# --- DLQ Endpoints ---


class DLQEntryResponse(BaseModel):
    dlq_id: str | None
    original_topic: str | None
    original_key: str | None
    error_type: str | None = None
    error_message: str | None = None
    source: str | None
    run_id: str | None
    attempt_count: int | None = None
    failed_at: str | None
    published_at: str | None = None


@router.get("/dlq", response_model=list[DLQEntryResponse], summary="List DLQ entries")
async def get_dlq(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    source: str | None = Query(default=None, description="Filter by source"),
    limit: int = Query(default=50, le=500),
) -> list[DLQEntryResponse]:
    """List dead letter queue entries for failed ingestion records."""
    from astraeus_marketdata.dlq import get_dlq_entries

    entries = await get_dlq_entries(session, limit=limit, source=source)

    return [
        DLQEntryResponse(
            dlq_id=entry.get("dlq_id"),
            original_topic=entry.get("original_topic"),
            original_key=entry.get("original_key"),
            error_type=(
                entry.get("error", {}).get("type") if isinstance(entry.get("error"), dict) else None
            ),
            error_message=(
                entry.get("error", {}).get("message")
                if isinstance(entry.get("error"), dict)
                else None
            ),
            source=entry.get("source"),
            run_id=entry.get("run_id"),
            attempt_count=entry.get("attempt_count"),
            failed_at=entry.get("failed_at"),
            published_at=entry.get("published_at"),
        )
        for entry in entries
    ]
