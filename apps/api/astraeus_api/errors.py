"""RFC 7807 problem-details handlers.

All errors crossing the HTTP boundary are translated into
``application/problem+json`` with a stable ``code`` and the active OTel
``trace_id`` so a user-facing error maps directly to a Jaeger search.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from astraeus_contracts import ProblemDetails
from astraeus_domain import AstraeusError
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from opentelemetry import trace
from starlette.exceptions import HTTPException as StarletteHTTPException

if TYPE_CHECKING:
    from fastapi import FastAPI, Request


_PROBLEM_MEDIA_TYPE = "application/problem+json"


def _current_trace_id() -> str | None:
    span = trace.get_current_span()
    ctx = span.get_span_context() if span is not None else None
    if ctx is None or not ctx.is_valid:
        return None
    return f"{ctx.trace_id:032x}"


def _problem_response(problem: ProblemDetails) -> ORJSONResponse:
    return ORJSONResponse(
        status_code=problem.status,
        content=jsonable_encoder(problem),
        media_type=_PROBLEM_MEDIA_TYPE,
    )


async def astraeus_error_handler(_request: Request, exc: Exception) -> ORJSONResponse:
    assert isinstance(exc, AstraeusError)
    problem = ProblemDetails(
        type=f"https://astraeus.dev/errors/{exc.code}",
        title=exc.code.rsplit(".", 1)[-1].replace("_", " ").title(),
        status=exc.status,
        detail=exc.detail,
        code=exc.code,
        trace_id=_current_trace_id(),
    )
    return _problem_response(problem)


async def http_exception_handler(_request: Request, exc: Exception) -> ORJSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    problem = ProblemDetails(
        type="about:blank",
        title=exc.detail if isinstance(exc.detail, str) else "HTTP Error",
        status=exc.status_code,
        detail=str(exc.detail) if exc.detail is not None else None,
        code=f"astraeus.http.{exc.status_code}",
        trace_id=_current_trace_id(),
    )
    return _problem_response(problem)


async def validation_exception_handler(_request: Request, exc: Exception) -> ORJSONResponse:
    assert isinstance(exc, RequestValidationError)
    problem = ProblemDetails(
        type="https://astraeus.dev/errors/astraeus.api.validation_failed",
        title="Validation Failed",
        status=422,
        detail="Request payload failed validation.",
        code="astraeus.api.validation_failed",
        trace_id=_current_trace_id(),
        errors=jsonable_encoder(exc.errors()),
    )
    return _problem_response(problem)


async def unhandled_exception_handler(_request: Request, exc: Exception) -> ORJSONResponse:
    problem = ProblemDetails(
        type="https://astraeus.dev/errors/astraeus.internal",
        title="Internal Server Error",
        status=500,
        detail="An unexpected error occurred.",
        code="astraeus.internal",
        trace_id=_current_trace_id(),
        exception_type=type(exc).__name__,
    )
    return _problem_response(problem)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AstraeusError, astraeus_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
