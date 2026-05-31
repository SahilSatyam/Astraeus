"""Event schemas and stream configuration for portfolio construction.

Defines Pydantic models for events produced and consumed by the Phase 4
portfolio construction pipeline, along with stream name constants and
consumer configuration.

Output streams:
  - portfolio.published.v1        (key: strategy_id) — TargetPortfolio
  - portfolio.rejections.v1       (key: strategy_id) — RiskRejection
  - portfolio.determinism_violations.v1 (key: strategy_id) — DeterminismViolation
  - pipeline.task.failed.v1       (key: strategy_id) — TaskFailure

Consumed streams:
  - signals.daily_batch.completed.v1 — SignalBatchCompleted (Phase 3)
  - views.published.v1              — View (Phase 6)
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Schema versions
# ---------------------------------------------------------------------------

DETERMINISM_VIOLATION_SCHEMA_VERSION = 1
TASK_FAILURE_SCHEMA_VERSION = 1
SIGNAL_BATCH_COMPLETED_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Output event schemas
# ---------------------------------------------------------------------------


class DeterminismViolation(BaseModel):
    """Emitted when a replay run produces a different output hash than stored.

    Topic: portfolio.determinism_violations.v1
    Key: strategy_id (bytes)

    Validates: Requirements 18.4, 18.5
    """

    schema_version: int = Field(
        default=DETERMINISM_VIOLATION_SCHEMA_VERSION,
        description="Schema version for evolution",
    )
    violation_id: UUID = Field(..., description="Unique violation identifier")
    strategy_id: str = Field(..., max_length=128, description="Strategy identifier")
    as_of_date: str = Field(..., description="Pipeline date in ISO format (YYYY-MM-DD)")
    task_name: str = Field(..., description="Task that produced divergent output")
    stored_hash: str = Field(..., description="Hash of the previously stored result")
    computed_hash: str = Field(..., description="Hash of the newly computed result")
    version: int = Field(..., description="Task run version that triggered detection")
    detected_at: datetime = Field(..., description="UTC timestamp when violation was detected")


class TaskFailure(BaseModel):
    """Emitted when a pipeline task exhausts all retry attempts.

    Topic: pipeline.task.failed.v1
    Key: strategy_id (bytes)

    Validates: Requirements 15.5, 15.6
    """

    schema_version: int = Field(
        default=TASK_FAILURE_SCHEMA_VERSION,
        description="Schema version for evolution",
    )
    task_id: UUID = Field(..., description="Unique task run identifier")
    strategy_id: str = Field(..., max_length=128, description="Strategy identifier")
    as_of_date: str = Field(..., description="Pipeline date in ISO format (YYYY-MM-DD)")
    task_name: str = Field(..., description="Name of the failed task")
    error_reason: str = Field(..., description="Human-readable failure reason")
    attempt_count: int = Field(..., ge=1, description="Number of attempts made before giving up")
    first_attempt_at: datetime = Field(..., description="UTC timestamp of the first attempt")
    failed_at: datetime = Field(..., description="UTC timestamp of the final failure")
    duration_ms: int | None = Field(
        default=None, description="Total wall-clock time across all attempts (ms)"
    )


# ---------------------------------------------------------------------------
# Consumed event schemas
# ---------------------------------------------------------------------------


class SignalBatchCompleted(BaseModel):
    """Consumed from Phase 3 to trigger the daily pipeline.

    Topic: signals.daily_batch.completed.v1
    Key: strategy_id (bytes)

    This event indicates that all signals for a given strategy and date
    have been computed and are ready for portfolio construction.
    """

    schema_version: int = Field(
        default=SIGNAL_BATCH_COMPLETED_SCHEMA_VERSION,
        description="Schema version for evolution",
    )
    strategy_id: str = Field(..., max_length=128, description="Strategy identifier")
    as_of_date: str = Field(..., description="Signal date in ISO format (YYYY-MM-DD)")
    signal_count: int = Field(..., ge=0, description="Number of signals in the batch")
    batch_id: UUID = Field(..., description="Unique batch identifier")
    completed_at: datetime = Field(..., description="UTC timestamp when batch processing completed")


# ---------------------------------------------------------------------------
# Topic configuration
# ---------------------------------------------------------------------------


class TopicConfig(BaseModel):
    """Configuration for a single event stream."""

    model_config = {"frozen": True}

    name: str
    key_field: str
    schema: type[BaseModel]
    direction: Literal["output", "input"]
    partitions: int = 16
    retention_ms: int = 7 * 24 * 60 * 60 * 1000  # 7 days default


# Output topics produced by Phase 4
TOPIC_PORTFOLIO_PUBLISHED = "portfolio.published.v1"
TOPIC_PORTFOLIO_REJECTIONS = "portfolio.rejections.v1"
TOPIC_DETERMINISM_VIOLATIONS = "portfolio.determinism_violations.v1"
TOPIC_TASK_FAILED = "pipeline.task.failed.v1"

# Consumed topics from upstream phases
TOPIC_SIGNAL_BATCH_COMPLETED = "signals.daily_batch.completed.v1"
TOPIC_VIEWS_PUBLISHED = "views.published.v1"


# ---------------------------------------------------------------------------
# Output topic registry
# ---------------------------------------------------------------------------

# Note: TargetPortfolio and RiskRejection schemas are defined in contracts.py.
# They are referenced here by topic name for the registry. Import them at
# runtime to avoid circular imports when contracts.py is populated.

OUTPUT_TOPICS: dict[str, dict] = {
    TOPIC_PORTFOLIO_PUBLISHED: {
        "key_field": "strategy_id",
        "direction": "output",
        "partitions": 16,
        "description": "Accepted target portfolios for downstream execution",
    },
    TOPIC_PORTFOLIO_REJECTIONS: {
        "key_field": "strategy_id",
        "direction": "output",
        "partitions": 16,
        "description": "Risk-rejected portfolios with failure details",
    },
    TOPIC_DETERMINISM_VIOLATIONS: {
        "key_field": "strategy_id",
        "direction": "output",
        "partitions": 4,
        "description": "Determinism violation alerts from replay runs",
    },
    TOPIC_TASK_FAILED: {
        "key_field": "strategy_id",
        "direction": "output",
        "partitions": 8,
        "description": "Pipeline task failures after retry exhaustion",
    },
}


# ---------------------------------------------------------------------------
# Consumer configuration
# ---------------------------------------------------------------------------


class ConsumerConfig(BaseModel):
    """Configuration for consuming an upstream event stream."""

    model_config = {"frozen": True}

    topic: str
    group_id: str
    key_field: str
    auto_offset_reset: Literal["earliest", "latest"] = "earliest"
    max_poll_interval_ms: int = 300_000  # 5 minutes
    session_timeout_ms: int = 30_000
    enable_auto_commit: bool = False


CONSUMER_SIGNAL_BATCH = ConsumerConfig(
    topic=TOPIC_SIGNAL_BATCH_COMPLETED,
    group_id="portfolio-construction.signals",
    key_field="strategy_id",
    auto_offset_reset="earliest",
    enable_auto_commit=False,
)

CONSUMER_VIEWS = ConsumerConfig(
    topic=TOPIC_VIEWS_PUBLISHED,
    group_id="portfolio-construction.views",
    key_field="strategy_id",
    auto_offset_reset="latest",
    enable_auto_commit=False,
)


# ---------------------------------------------------------------------------
# Schema registry for portfolio domain topics
# ---------------------------------------------------------------------------

PORTFOLIO_SCHEMA_REGISTRY: dict[str, type[BaseModel]] = {
    TOPIC_DETERMINISM_VIOLATIONS: DeterminismViolation,
    TOPIC_TASK_FAILED: TaskFailure,
    TOPIC_SIGNAL_BATCH_COMPLETED: SignalBatchCompleted,
    # TargetPortfolio and RiskRejection are registered once contracts.py is populated:
    # TOPIC_PORTFOLIO_PUBLISHED: TargetPortfolio,
    # TOPIC_PORTFOLIO_REJECTIONS: RiskRejection,
}


def get_portfolio_schema(topic: str) -> type[BaseModel] | None:
    """Look up the schema class for a portfolio domain topic."""
    return PORTFOLIO_SCHEMA_REGISTRY.get(topic)


def validate_portfolio_event(topic: str, payload: dict) -> BaseModel:
    """Validate a payload against the registered schema for a portfolio topic.

    Raises:
        ValueError: If topic has no registered schema.
        pydantic.ValidationError: If payload doesn't match schema.
    """
    schema = get_portfolio_schema(topic)
    if schema is None:
        raise ValueError(f"No schema registered for portfolio topic: {topic}")
    return schema.model_validate(payload)
