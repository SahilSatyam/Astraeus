"""Point-in-time validation logic.

Enforces that every input to the portfolio construction pipeline carries
an `as_of_ts` that is <= the target pipeline timestamp. This prevents
lookahead leakage — the most dangerous class of backtest bug.

PIT semantics are enforced at the data-access layer (Phase 2), but this
module provides an additional defense-in-depth check at the pipeline boundary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class PITViolationError(Exception):
    """Raised when an input violates point-in-time constraints.

    Attributes:
        field_name: The field that violated PIT.
        input_ts: The timestamp on the input.
        target_ts: The pipeline target timestamp.
    """

    def __init__(self, field_name: str, input_ts: datetime, target_ts: datetime) -> None:
        self.field_name = field_name
        self.input_ts = input_ts
        self.target_ts = target_ts
        super().__init__(
            f"PIT violation: {field_name} has as_of_ts={input_ts.isoformat()} "
            f"which is after target_ts={target_ts.isoformat()}"
        )


def validate_pit_timestamp(
    field_name: str,
    input_ts: datetime,
    target_ts: datetime,
) -> None:
    """Validate that an input timestamp does not exceed the target timestamp.

    Args:
        field_name: Human-readable name of the input being validated.
        input_ts: The as_of_ts on the input data.
        target_ts: The pipeline's target timestamp (e.g., market close).

    Raises:
        PITViolationError: If input_ts > target_ts.
    """
    if input_ts > target_ts:
        raise PITViolationError(
            field_name=field_name,
            input_ts=input_ts,
            target_ts=target_ts,
        )


def validate_pit_context(
    target_ts: datetime,
    covariance_as_of: datetime | None = None,
    signals_as_of: datetime | None = None,
    views_as_of: list[datetime] | None = None,
    prices_as_of: datetime | None = None,
    beta_as_of: datetime | None = None,
) -> list[str]:
    """Validate all pipeline inputs against the target timestamp.

    Checks each provided timestamp and collects all violations rather than
    failing on the first one. This gives operators a complete picture of
    what's wrong.

    Args:
        target_ts: The pipeline's target timestamp.
        covariance_as_of: Timestamp of the covariance estimate.
        signals_as_of: Timestamp of the signal batch.
        views_as_of: List of timestamps for BL views.
        prices_as_of: Timestamp of the price snapshot.
        beta_as_of: Timestamp of the beta estimates.

    Returns:
        List of violation descriptions (empty if all pass).

    Raises:
        PITViolationError: If any input violates PIT and strict mode is desired.
            Callers can choose to raise based on the returned list instead.
    """
    violations: list[str] = []

    checks: list[tuple[str, datetime | None]] = [
        ("covariance", covariance_as_of),
        ("signals", signals_as_of),
        ("prices", prices_as_of),
        ("beta", beta_as_of),
    ]

    for field_name, ts in checks:
        if ts is not None:
            # Normalize timezone awareness for comparison
            ts_compare = ts.replace(tzinfo=None) if ts.tzinfo else ts
            target_compare = target_ts.replace(tzinfo=None) if target_ts.tzinfo else target_ts
            if ts_compare > target_compare:
                msg = (
                    f"PIT violation: {field_name} as_of_ts={ts.isoformat()} "
                    f"> target_ts={target_ts.isoformat()}"
                )
                violations.append(msg)
                logger.error("pit_violation", field=field_name, input_ts=ts, target_ts=target_ts)

    if views_as_of:
        for i, view_ts in enumerate(views_as_of):
            view_compare = view_ts.replace(tzinfo=None) if view_ts.tzinfo else view_ts
            target_compare = target_ts.replace(tzinfo=None) if target_ts.tzinfo else target_ts
            if view_compare > target_compare:
                msg = (
                    f"PIT violation: view[{i}] as_of_ts={view_ts.isoformat()} "
                    f"> target_ts={target_ts.isoformat()}"
                )
                violations.append(msg)
                logger.error(
                    "pit_violation", field=f"view[{i}]", input_ts=view_ts, target_ts=target_ts
                )

    return violations


def enforce_pit_strict(
    target_ts: datetime,
    **kwargs: Any,
) -> None:
    """Strict PIT enforcement — raises on any violation.

    Convenience wrapper around validate_pit_context that raises
    PITViolationError on the first detected violation.

    Args:
        target_ts: The pipeline's target timestamp.
        **kwargs: Keyword arguments passed to validate_pit_context.

    Raises:
        PITViolationError: If any input violates PIT constraints.
    """
    violations = validate_pit_context(target_ts=target_ts, **kwargs)
    if violations:
        # Raise on the first violation for a clear error message
        raise PITViolationError(
            field_name=violations[0].split(":")[1].strip().split(" ")[0],
            input_ts=target_ts,  # Approximate — the real ts is in the message
            target_ts=target_ts,
        )
