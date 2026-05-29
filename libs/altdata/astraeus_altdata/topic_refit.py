"""Topic model refit scheduler.

Re-fits BERTopic every 30 days on a 90-day rolling window.
Each refit produces a new model_run_id — never overwrites.
Topic drift is computed and emitted as a metric.

Cadence: triggered by a cron job or the nightly worker.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("astraeus.altdata.topic_refit")

# Refit cadence
REFIT_INTERVAL_DAYS = 30
FIT_WINDOW_DAYS = 90

# Drift alert threshold
DRIFT_ALERT_THRESHOLD = 0.30


async def should_refit(session: AsyncSession) -> bool:
    """Check if a topic model refit is due.

    Returns True if the last refit was > REFIT_INTERVAL_DAYS ago or never ran.
    """
    result = await session.execute(
        text("SELECT max(fit_at) FROM topic_model_run")
    )
    last_fit = result.scalar_one_or_none()

    if last_fit is None:
        logger.info("topic_refit_needed", reason="no_previous_run")
        return True

    days_since = (datetime.now(tz=UTC) - last_fit).days
    if days_since >= REFIT_INTERVAL_DAYS:
        logger.info("topic_refit_needed", reason="interval_exceeded", days_since=days_since)
        return True

    logger.debug("topic_refit_not_needed", days_since=days_since)
    return False


async def get_chunks_for_window(
    session: AsyncSession,
    window_days: int = FIT_WINDOW_DAYS,
) -> list[dict[str, object]]:
    """Fetch document chunks from the last `window_days` for topic modeling."""
    cutoff = datetime.now(tz=UTC) - timedelta(days=window_days)

    result = await session.execute(
        text("""
            SELECT dc.chunk_id, dc.text
            FROM document_chunk dc
            JOIN raw_document rd ON rd.doc_id = dc.doc_id
            WHERE rd.available_at >= :cutoff
            ORDER BY rd.available_at DESC
            LIMIT 50000
        """),
        {"cutoff": cutoff},
    )

    rows = result.fetchall()
    return [{"chunk_id": row.chunk_id, "text": row.text} for row in rows]


async def get_previous_summary(session: AsyncSession) -> dict[int, list[str]] | None:
    """Get the topic summary from the most recent model run for drift comparison."""
    result = await session.execute(
        text("""
            SELECT topic_summary
            FROM topic_model_run
            ORDER BY fit_at DESC
            LIMIT 1
        """)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None

    # Convert JSON keys back to int
    return {int(k): v for k, v in row.items()} if isinstance(row, dict) else None


async def persist_refit_result(
    session: AsyncSession,
    model_run_id: uuid.UUID,
    fit_window_from: date,
    fit_window_to: date,
    n_topics: int,
    topic_summary: dict[int, list[str]],
    assignments: list[tuple[uuid.UUID, int, float]],
) -> None:
    """Persist a topic model refit result to the database.

    Stores the model run metadata and all chunk-topic assignments.
    """
    # Insert model run
    await session.execute(
        text("""
            INSERT INTO topic_model_run (model_run_id, fit_window_from, fit_window_to, n_topics, topic_summary)
            VALUES (:model_run_id, :fit_from, :fit_to, :n_topics, :summary::jsonb)
        """),
        {
            "model_run_id": model_run_id,
            "fit_from": fit_window_from,
            "fit_to": fit_window_to,
            "n_topics": n_topics,
            "summary": _serialize_summary(topic_summary),
        },
    )

    # Batch insert assignments
    if assignments:
        values_parts = []
        params: dict[str, object] = {"model_run_id": model_run_id}
        for i, (chunk_id, topic_id, probability) in enumerate(assignments):
            values_parts.append(f"(:chunk_{i}, :topic_{i}, :run_id, :prob_{i})")
            params[f"chunk_{i}"] = chunk_id
            params[f"topic_{i}"] = topic_id
            params[f"prob_{i}"] = probability
            params["run_id"] = model_run_id

        # Insert in batches of 1000
        batch_size = 1000
        for batch_start in range(0, len(values_parts), batch_size):
            batch = values_parts[batch_start : batch_start + batch_size]
            batch_params: dict[str, object] = {"model_run_id": model_run_id}
            for i, (chunk_id, topic_id, probability) in enumerate(
                assignments[batch_start : batch_start + batch_size]
            ):
                batch_params[f"chunk_{i}"] = chunk_id
                batch_params[f"topic_{i}"] = topic_id
                batch_params[f"prob_{i}"] = probability

            sql = (
                "INSERT INTO topic_assignment (chunk_id, topic_id, model_run_id, probability) "
                "VALUES " + ", ".join(
                    f"(:chunk_{i}, :topic_{i}, :model_run_id, :prob_{i})"
                    for i in range(len(batch))
                )
                + " ON CONFLICT DO NOTHING"
            )
            await session.execute(text(sql), batch_params)

    await session.commit()

    logger.info(
        "topic_refit_persisted",
        model_run_id=str(model_run_id),
        n_topics=n_topics,
        n_assignments=len(assignments),
    )


async def run_refit(session: AsyncSession) -> dict[str, object] | None:
    """Execute a full topic model refit cycle.

    1. Check if refit is due
    2. Fetch chunks from the rolling window
    3. Fit BERTopic
    4. Compute drift from previous run
    5. Persist results
    6. Return metrics

    Returns None if refit is not due, otherwise returns metrics dict.
    """
    if not await should_refit(session):
        return None

    # Fetch chunks
    chunks = await get_chunks_for_window(session)
    if len(chunks) < 100:
        logger.warning("topic_refit_skipped", reason="insufficient_chunks", n_chunks=len(chunks))
        return {"skipped": True, "reason": "insufficient_chunks", "n_chunks": len(chunks)}

    # Import topic modeler (heavy dependency, lazy load)
    from astraeus_nlp.topic import TopicModeler

    modeler = TopicModeler(min_topic_size=max(5, len(chunks) // 50))

    texts = [c["text"] for c in chunks]
    chunk_ids = [c["chunk_id"] for c in chunks]

    window_to = date.today()
    window_from = window_to - timedelta(days=FIT_WINDOW_DAYS)

    # Fit
    result = modeler.fit_transform(
        texts=texts,  # type: ignore[arg-type]
        chunk_ids=chunk_ids,  # type: ignore[arg-type]
        window_from=window_from,
        window_to=window_to,
    )

    # Compute drift
    previous_summary = await get_previous_summary(session)
    drift_score = 0.0
    if previous_summary:
        drift_score = modeler.compute_drift(previous_summary, result.topic_summary)

    # Persist
    assignments = [
        (a.chunk_id, a.topic_id, a.probability) for a in result.assignments
    ]
    await persist_refit_result(
        session=session,
        model_run_id=result.model_run_id,
        fit_window_from=window_from,
        fit_window_to=window_to,
        n_topics=result.n_topics,
        topic_summary=result.topic_summary,
        assignments=assignments,
    )

    # Alert on high drift
    if drift_score > DRIFT_ALERT_THRESHOLD:
        logger.warning(
            "topic_drift_alert",
            drift_score=round(drift_score, 3),
            threshold=DRIFT_ALERT_THRESHOLD,
            model_run_id=str(result.model_run_id),
        )

    metrics = {
        "model_run_id": str(result.model_run_id),
        "n_topics": result.n_topics,
        "n_assignments": len(assignments),
        "n_chunks_processed": len(chunks),
        "drift_score": round(drift_score, 3),
        "drift_alert": drift_score > DRIFT_ALERT_THRESHOLD,
        "window": f"{window_from} to {window_to}",
    }

    logger.info("topic_refit_complete", **metrics)
    return metrics


def _serialize_summary(summary: dict[int, list[str]]) -> str:
    """Serialize topic summary to JSON string for Postgres JSONB."""
    import json

    return json.dumps({str(k): v for k, v in summary.items()})
