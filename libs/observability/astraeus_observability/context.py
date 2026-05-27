"""Request-scoped context helpers.

structlog reads contextvars via ``merge_contextvars`` in the processor chain.
Setting ``request_id`` and ``trace_id`` here makes them visible on every log
line emitted while the context is active.
"""

from __future__ import annotations

import structlog


def bind_request_context(
    *,
    request_id: str,
    trace_id: str | None = None,
    span_id: str | None = None,
) -> None:
    """Bind per-request identifiers to the structlog contextvars store."""
    bound: dict[str, str] = {"request_id": request_id}
    if trace_id is not None:
        bound["trace_id"] = trace_id
    if span_id is not None:
        bound["span_id"] = span_id
    structlog.contextvars.bind_contextvars(**bound)


def clear_request_context() -> None:
    """Clear request-scoped contextvars at the end of a request."""
    structlog.contextvars.clear_contextvars()
