"""ASGI middleware: request_id, structlog binding."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from astraeus_observability import bind_request_context, clear_request_context
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from starlette.middleware.base import RequestResponseEndpoint
    from starlette.requests import Request
    from starlette.responses import Response


_REQUEST_ID_HEADER = "x-request-id"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind request_id + trace_id to structlog context for the request scope."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(_REQUEST_ID_HEADER) or uuid.uuid4().hex

        span = trace.get_current_span()
        ctx = span.get_span_context() if span is not None else None
        trace_id = f"{ctx.trace_id:032x}" if ctx is not None and ctx.is_valid else None
        span_id = f"{ctx.span_id:016x}" if ctx is not None and ctx.is_valid else None

        bind_request_context(request_id=request_id, trace_id=trace_id, span_id=span_id)
        try:
            response = await call_next(request)
        finally:
            clear_request_context()

        response.headers[_REQUEST_ID_HEADER] = request_id
        return response
