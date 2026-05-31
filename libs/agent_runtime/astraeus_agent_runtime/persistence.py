"""Run-trace persistence — writes agent runs, steps, and cost ledger to Postgres.

This module bridges the in-memory orchestrator state to the append-only
trace tables. Every run, step, LLM call, and tool call is persisted for
observability and replay.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("astraeus.agent_runtime.persistence")


async def persist_run(
    session: AsyncSession,
    run_result: dict[str, Any],
) -> None:
    """Persist a completed workflow run to the agent_run table."""
    await session.execute(
        text("""
            INSERT INTO agent_run (run_id, workflow_key, status, inputs, output,
                                   output_schema_version, cost_usd, duration_ms,
                                   created_at, completed_at)
            VALUES (:run_id, :workflow_key, :status, :inputs::jsonb, :output::jsonb,
                    :schema_version, :cost_usd, :duration_ms, :created_at, :completed_at)
            ON CONFLICT (run_id) DO UPDATE SET
                status = EXCLUDED.status,
                output = EXCLUDED.output,
                cost_usd = EXCLUDED.cost_usd,
                duration_ms = EXCLUDED.duration_ms,
                completed_at = EXCLUDED.completed_at
        """),
        {
            "run_id": run_result["run_id"],
            "workflow_key": run_result["workflow_key"],
            "status": run_result["status"],
            "inputs": _json_dumps(run_result.get("inputs")),
            "output": _json_dumps(run_result.get("output")),
            "schema_version": "v1",
            "cost_usd": run_result.get("cost_usd", 0.0),
            "duration_ms": int(run_result.get("duration_ms", 0)),
            "created_at": run_result.get("created_at", datetime.now(tz=UTC).isoformat()),
            "completed_at": datetime.now(tz=UTC),
        },
    )
    await session.flush()


async def persist_steps(
    session: AsyncSession,
    run_id: str,
    steps: list[dict[str, Any]],
) -> None:
    """Persist agent steps for a run."""
    for ordinal, step in enumerate(steps):
        await session.execute(
            text("""
                INSERT INTO agent_step (step_id, run_id, agent_name, ordinal, status,
                                        cost_usd, duration_ms)
                VALUES (:step_id, :run_id, :agent_name, :ordinal, :status,
                        :cost_usd, :duration_ms)
                ON CONFLICT (step_id) DO NOTHING
            """),
            {
                "step_id": step.get("step_id", str(uuid.uuid4())),
                "run_id": run_id,
                "agent_name": step.get("agent_name", "unknown"),
                "ordinal": ordinal,
                "status": step.get("status", "completed"),
                "cost_usd": step.get("cost_usd", 0.0),
                "duration_ms": int(step.get("duration_ms", 0)),
            },
        )
    await session.flush()


async def persist_llm_calls(
    session: AsyncSession,
    run_id: str,
    call_records: list[Any],
) -> None:
    """Persist LLM call records to the cost ledger."""
    for record in call_records:
        await session.execute(
            text("""
                INSERT INTO llm_call_ledger (run_id, step_id, agent_name, prompt_key,
                                             prompt_version, model, input_tokens,
                                             output_tokens, cache_read_tokens,
                                             cache_write_tokens, cost_usd, latency_ms,
                                             ttft_ms, status, error_class)
                VALUES (:run_id, :step_id, :agent_name, :prompt_key, :prompt_version,
                        :model, :input_tokens, :output_tokens, :cache_read_tokens,
                        :cache_write_tokens, :cost_usd, :latency_ms, :ttft_ms,
                        :status, :error_class)
            """),
            {
                "run_id": str(record.run_id) if record.run_id else run_id,
                "step_id": str(record.step_id) if record.step_id else str(uuid.uuid4()),
                "agent_name": record.agent_name,
                "prompt_key": record.prompt_key,
                "prompt_version": record.prompt_version,
                "model": record.model,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "cache_read_tokens": record.cache_read_tokens,
                "cache_write_tokens": record.cache_write_tokens,
                "cost_usd": record.cost_usd,
                "latency_ms": int(record.latency_ms),
                "ttft_ms": int(record.ttft_ms) if record.ttft_ms else None,
                "status": record.status,
                "error_class": record.error_class,
            },
        )
    await session.flush()


async def load_run(session: AsyncSession, run_id: str) -> dict[str, Any] | None:
    """Load a run from the database."""
    result = await session.execute(
        text("""
            SELECT run_id, workflow_key, status, inputs, output,
                   output_schema_version, cost_usd, duration_ms,
                   created_at, completed_at
            FROM agent_run
            WHERE run_id = :run_id
        """),
        {"run_id": run_id},
    )
    row = result.fetchone()
    if row is None:
        return None

    return {
        "run_id": str(row.run_id),
        "workflow_key": row.workflow_key,
        "status": row.status,
        "inputs": row.inputs,
        "output": row.output,
        "output_schema_version": row.output_schema_version,
        "cost_usd": float(row.cost_usd) if row.cost_usd else 0.0,
        "duration_ms": row.duration_ms or 0,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


async def load_run_steps(session: AsyncSession, run_id: str) -> list[dict[str, Any]]:
    """Load steps for a run from the database."""
    result = await session.execute(
        text("""
            SELECT step_id, agent_name, ordinal, status, cost_usd, duration_ms
            FROM agent_step
            WHERE run_id = :run_id
            ORDER BY ordinal
        """),
        {"run_id": run_id},
    )
    rows = result.fetchall()
    return [
        {
            "step_id": str(row.step_id),
            "agent_name": row.agent_name,
            "ordinal": row.ordinal,
            "status": row.status,
            "cost_usd": float(row.cost_usd) if row.cost_usd else 0.0,
            "duration_ms": row.duration_ms or 0,
        }
        for row in rows
    ]


def _json_dumps(obj: Any) -> str | None:
    """Serialize to JSON string for Postgres JSONB columns."""
    if obj is None:
        return None
    import json

    return json.dumps(obj, default=str)
