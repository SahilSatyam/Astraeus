"""Structlog configuration.

The processor chain is the contract Phase 1+ services depend on. Order matters:

1. ``add_log_level`` — promote ``log.info(...)`` etc. to a ``level`` key.
2. ``TimeStamper(fmt='iso', utc=True)`` — every line carries an ISO-8601 UTC
   timestamp.
3. ``add_logger_name`` — attach the dotted module path as ``logger``.
4. :class:`Redactor` — scrub known-sensitive keys regardless of caller
   discipline.
5. ``format_exc_info`` — render exceptions in a structured way.
6. JSON renderer (prod / CI) or ``ConsoleRenderer`` (local dev).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

import structlog

from astraeus_observability.processors import Redactor

if TYPE_CHECKING:
    from astraeus_config import ObservabilitySettings


def configure_logging(settings: ObservabilitySettings, *, service: str) -> None:
    """Configure structlog for the calling process.

    Idempotent — safe to call from a test fixture as well as service startup.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.stdlib.add_logger_name,
        _service_binder(service),
        Redactor(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    renderer: structlog.types.Processor
    if settings.log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(_level_to_int(settings.log_level)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _service_binder(service: str) -> structlog.types.Processor:
    def _bind(
        _logger: Any,
        _name: str,
        event_dict: structlog.types.EventDict,
    ) -> structlog.types.EventDict:
        event_dict.setdefault("service", service)
        return event_dict

    return _bind


def _level_to_int(level: str) -> int:
    return cast("int", getattr(logging, level))
