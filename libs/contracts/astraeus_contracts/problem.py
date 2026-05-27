"""RFC 7807 Problem Details model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProblemDetails(BaseModel):
    """RFC 7807 problem details object.

    Returned with ``Content-Type: application/problem+json`` whenever a service
    surfaces an :class:`astraeus_domain.AstraeusError` or any unhandled exception.
    """

    model_config = ConfigDict(extra="allow")

    type: str = Field(
        default="about:blank", description="A URI reference identifying the problem type."
    )
    title: str = Field(..., description="A short, human-readable summary of the problem.")
    status: int = Field(..., ge=100, le=599)
    detail: str | None = None
    instance: str | None = None
    code: str = Field(
        ..., description="Stable Astraeus error code (e.g. ``astraeus.api.not_found``)."
    )
    trace_id: str | None = Field(default=None, description="OTel trace id of the failing request.")
